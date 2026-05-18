"""Tests for chaos_librarian.determinism.ids.IdAllocator."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.replay_bundle import AllocTraceEntry
from chaos_librarian.determinism.ids import IdAllocator, IdAllocatorOverflow
from chaos_librarian.determinism.trace import TraceRecorder


class TestAllocatorBasicSequence:
    """First call returns _0001; subsequent calls increment monotonically.

    WHY: lexicographic sort of allocator-owned IDs (version, location,
    sidecar, mutation) is a downstream assumption in journal ordering and
    manifest snapshotting. A reset or skip would invalidate ordered diffs.
    """

    def test_first_call_returns_0001(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        assert alloc.next_version_id() == "version_0001"
        assert alloc.next_location_id() == "location_0001"
        assert alloc.next_sidecar_id() == "sidecar_0001"
        assert alloc.next_mutation_id() == "mutation_0001"

    def test_sequential_calls_increment_within_namespace(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        ids = [alloc.next_version_id() for _ in range(3)]
        assert ids == ["version_0001", "version_0002", "version_0003"]

    def test_id_is_zero_padded_to_four_digits(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        last = ""
        for _ in range(11):
            last = alloc.next_version_id()
        assert last == "version_0011"


class TestNamespaceIndependence:
    """Each namespace has its own counter; bumping one never moves another.

    WHY: scenario authors interleave version/location/sidecar/mutation
    allocations freely; cross-talk would silently desync identifier streams
    from one another and from the trace.
    """

    def test_other_namespaces_unaffected_by_version_calls(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(5):
            alloc.next_version_id()
        assert alloc.next_location_id() == "location_0001"
        assert alloc.next_sidecar_id() == "sidecar_0001"
        assert alloc.next_mutation_id() == "mutation_0001"


class TestAllocatorTraceFidelity:
    """Each allocation appends exactly one AllocTraceEntry with the right stream/value.

    WHY: trace fidelity is the load-bearing input to Sprint 4's replay
    divergence detection. A missing or mislabelled entry would silently mask
    a real bug.
    """

    def test_allocation_appends_alloc_entry(self) -> None:
        rec = TraceRecorder()
        alloc = IdAllocator(recorder=rec)
        result = alloc.next_version_id()
        (entry,) = rec.entries()
        assert isinstance(entry, AllocTraceEntry)
        assert entry.kind == "alloc"
        assert entry.stream == "version"
        assert entry.value == result

    def test_multiple_allocations_in_call_order(self) -> None:
        rec = TraceRecorder()
        alloc = IdAllocator(recorder=rec)
        alloc.next_version_id()
        alloc.next_location_id()
        alloc.next_version_id()
        streams = [e.stream for e in rec.entries()]
        values = [e.value for e in rec.entries()]
        assert streams == ["version", "location", "version"]
        assert values == ["version_0001", "location_0001", "version_0002"]


class TestAllocatorOverflow:
    """The 10,000th call into a namespace raises IdAllocatorOverflow.

    WHY: 4-digit width keeps lexicographic sort stable across allocator-owned
    IDs. Silently producing ``version_10000`` would break sort order in
    downstream tools and contract consumers.
    """

    def test_overflow_after_9999_allocations(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(9_999):
            alloc.next_version_id()
        with pytest.raises(IdAllocatorOverflow) as excinfo:
            alloc.next_version_id()
        assert "version" in str(excinfo.value)

    def test_overflow_does_not_affect_other_namespaces(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(9_999):
            alloc.next_version_id()
        with pytest.raises(IdAllocatorOverflow):
            alloc.next_version_id()
        # location counter must still start at 1.
        assert alloc.next_location_id() == "location_0001"
