"""Property tests for IdAllocator interleaving stability."""

from __future__ import annotations

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from chaos_librarian.determinism.ids import IdAllocator
from chaos_librarian.determinism.trace import TraceRecorder

_METHODS = {
    "version": "next_version_id",
    "location": "next_location_id",
    "sidecar": "next_sidecar_id",
    "mutation": "next_mutation_id",
}


@given(
    calls=st.lists(
        st.sampled_from(list(_METHODS)),
        min_size=0,
        max_size=200,
    )
)
@settings(max_examples=200, deadline=None)
def test_allocator_output_depends_only_on_per_namespace_counts(calls: list[str]) -> None:
    """For any interleaving of next_*_id() calls across the four namespaces,
    the resulting ID list is determined entirely by per-namespace counts.

    WHY: this is the operational form of the "allocator order-stability"
    guarantee. If a future change accidentally couples two namespaces (e.g.,
    a shared counter), this test will catch it.
    """
    alloc = IdAllocator(recorder=TraceRecorder())
    actual: list[str] = []
    for namespace in calls:
        method = getattr(alloc, _METHODS[namespace])
        actual.append(method())

    # Hand-rolled per-namespace counter — the reference implementation.
    reference_counters: Counter[str] = Counter()
    expected: list[str] = []
    for namespace in calls:
        reference_counters[namespace] += 1
        expected.append(f"{namespace}_{reference_counters[namespace]:04d}")

    assert actual == expected
