"""Monotonic ID allocator with one independent counter per namespace.

The allocator owns only the four namespaces whose IDs have no source in
the scenario YAML — ``version``, ``location``, ``sidecar``, ``mutation``.
The other four oracle namespaces (``work``, ``variant``, ``bundle``,
``asset``) are scenario-authored ``str`` fields on the Scenario model
and flow verbatim through the timeline into the manifest; the allocator
never generates or mutates those values.
"""

from __future__ import annotations

from chaos_librarian.determinism.trace import TraceRecorder
from chaos_librarian.errors import ChaosLibrarianError

_MAX_PER_NAMESPACE = 9_999
# Zero-pad width derived from the max so the two cannot drift apart.
_ID_PAD_WIDTH = len(str(_MAX_PER_NAMESPACE))
_NAMESPACES = ("version", "location", "sidecar", "mutation")


class IdAllocatorOverflow(ChaosLibrarianError):
    """Raised when a namespace counter would advance past 9_999."""


class IdAllocator:
    """Per-namespace counter-only allocator."""

    def __init__(self, recorder: TraceRecorder) -> None:
        self._recorder = recorder
        self._counters: dict[str, int] = dict.fromkeys(_NAMESPACES, 0)

    def _allocate(self, namespace: str) -> str:
        current = self._counters[namespace]
        if current >= _MAX_PER_NAMESPACE:
            raise IdAllocatorOverflow(
                f"namespace {namespace!r} exhausted at {current} allocations "
                f"(max {_MAX_PER_NAMESPACE} per namespace)"
            )
        next_n = current + 1
        self._counters[namespace] = next_n
        allocated = f"{namespace}_{next_n:0{_ID_PAD_WIDTH}d}"
        self._recorder.record_alloc(stream=namespace, value=allocated)
        return allocated

    def next_version_id(self) -> str:
        return self._allocate("version")

    def next_location_id(self) -> str:
        return self._allocate("location")

    def next_sidecar_id(self) -> str:
        return self._allocate("sidecar")

    def next_mutation_id(self) -> str:
        return self._allocate("mutation")
