"""Tests for chaos_librarian.determinism.trace.TraceRecorder."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.replay_bundle import (
    AllocTraceEntry,
    MaterializerTraceEntry,
    RngTraceEntry,
)
from chaos_librarian.determinism.trace import TraceRecorder


class TestRecorderEntryDispatch:
    """Each record_* method appends the correct discriminated-union subclass.

    WHY: downstream sprints embed these entries verbatim in a ReplayBundle;
    the wrong subclass would break the bundle's discriminator-based oneOf.
    """

    def test_record_rng_appends_rng_entry(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="video_source", value="0.5")
        (entry,) = rec.entries()
        assert isinstance(entry, RngTraceEntry)
        assert entry.kind == "rng"
        assert entry.stream == "video_source"
        assert entry.value == "0.5"

    def test_record_alloc_appends_alloc_entry(self) -> None:
        rec = TraceRecorder()
        rec.record_alloc(stream="version", value="version_0001")
        (entry,) = rec.entries()
        assert isinstance(entry, AllocTraceEntry)
        assert entry.kind == "alloc"
        assert entry.stream == "version"
        assert entry.value == "version_0001"

    def test_record_materializer_appends_materializer_entry(self) -> None:
        rec = TraceRecorder()
        rec.record_materializer(stream="ffmpeg", value="ok", exit_code=0)
        (entry,) = rec.entries()
        assert isinstance(entry, MaterializerTraceEntry)
        assert entry.kind == "materializer"
        assert entry.stream == "ffmpeg"
        assert entry.value == "ok"
        assert entry.exit_code == 0


class TestRecorderOrderAndLen:
    """Entries are recorded in call order; __len__ matches.

    WHY: trace fidelity is a load-bearing determinism guarantee — Sprint 4's
    replay compares traces position-by-position to detect divergence.
    """

    def test_entries_preserve_call_order(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        rec.record_alloc(stream="version", value="version_0001")
        rec.record_rng(stream="a", value="2")
        kinds = [e.kind for e in rec.entries()]
        assert kinds == ["rng", "alloc", "rng"]

    def test_len_matches_entry_count(self) -> None:
        rec = TraceRecorder()
        assert len(rec) == 0
        rec.record_rng(stream="a", value="1")
        assert len(rec) == 1
        rec.record_alloc(stream="version", value="version_0001")
        assert len(rec) == 2


class TestRecorderSnapshotIsImmutable:
    """entries() returns an immutable tuple snapshot, not the internal list.

    WHY: the recorder is the only writer (closed API). Returning a list
    would let third parties mutate the recorded sequence after the fact,
    contradicting the determinism guarantee.
    """

    def test_entries_returns_tuple(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        assert isinstance(rec.entries(), tuple)

    def test_snapshot_cannot_be_appended_to(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        snapshot = rec.entries()
        with pytest.raises(AttributeError):
            snapshot.append("anything")  # ty: ignore[unresolved-attribute]

    def test_snapshot_does_not_reflect_later_records(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        snapshot = rec.entries()
        rec.record_rng(stream="a", value="2")
        assert len(snapshot) == 1
