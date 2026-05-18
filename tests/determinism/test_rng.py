"""Tests for chaos_librarian.determinism.rng (RngStream + RngStreams)."""

from __future__ import annotations

import random

from chaos_librarian.contract.replay_bundle import RngTraceEntry
from chaos_librarian.determinism.rng import RngStream, RngStreams
from chaos_librarian.determinism.trace import TraceRecorder


class TestStreamCache:
    """RngStreams returns the same RngStream instance per name.

    WHY: stream identity makes the per-stream call sequence well-defined.
    Returning a fresh instance per call would silently restart the underlying
    random.Random on every stream() lookup, defeating determinism.
    """

    def test_same_name_returns_same_instance(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        assert streams.stream("video_source") is streams.stream("video_source")

    def test_distinct_names_return_distinct_instances(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        assert streams.stream("a") is not streams.stream("b")


class TestSameSeedSameDraws:
    """Two RngStreams built from the same seed produce identical draws.

    WHY: this is the operational form of the "same seed → same RNG draws"
    determinism guarantee that bit-identical plan-only bundles bottom out in.
    """

    def test_random_draws_match(self) -> None:
        a = RngStreams(resolved_seed=42, recorder=TraceRecorder()).stream("video_source")
        b = RngStreams(resolved_seed=42, recorder=TraceRecorder()).stream("video_source")
        assert [a.random() for _ in range(20)] == [b.random() for _ in range(20)]

    def test_randint_draws_match(self) -> None:
        a = RngStreams(resolved_seed=99, recorder=TraceRecorder()).stream("audio_source")
        b = RngStreams(resolved_seed=99, recorder=TraceRecorder()).stream("audio_source")
        assert [a.randint(0, 100) for _ in range(20)] == [b.randint(0, 100) for _ in range(20)]


class TestSubSeedDivergesByName:
    """Different stream names under the same seed produce different draws.

    WHY: the sub-seed derivation (sha256(seed/name)) is what gives Sprint 5/6
    additive freedom — adding a new stream cannot perturb existing ones.
    """

    def test_different_names_diverge(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        a_draws = [streams.stream("a").random() for _ in range(20)]
        b_draws = [streams.stream("b").random() for _ in range(20)]
        assert a_draws != b_draws


class TestTraceFidelity:
    """Every documented draw records exactly one RngTraceEntry with value=repr(returned).

    WHY: trace fidelity is the input to Sprint 4 replay divergence detection.
    A missing or mis-labelled entry would silently mask a real bug; an extra
    entry would invalidate position-based trace comparison.
    """

    def test_random_records_one_entry(self) -> None:
        rec = TraceRecorder()
        streams = RngStreams(resolved_seed=42, recorder=rec)
        v = streams.stream("video_source").random()
        (entry,) = rec.entries()
        assert isinstance(entry, RngTraceEntry)
        assert entry.kind == "rng"
        assert entry.stream == "video_source"
        assert entry.value == repr(v)

    def test_each_documented_method_records_one_entry(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=42, recorder=rec).stream("metadata")
        s.random()
        s.randint(0, 10)
        s.randrange(10)
        s.randrange(2, 10)
        s.randrange(2, 10, 2)
        s.randbytes(4)
        s.choice([1, 2, 3])
        s.choices([1, 2, 3], k=2)
        s.sample([1, 2, 3], 2)
        s.uniform(0.0, 1.0)
        s.gauss(0.0, 1.0)
        assert len(rec) == 11
        assert all(e.kind == "rng" for e in rec.entries())
        assert all(e.stream == "metadata" for e in rec.entries())

    def test_value_is_repr_of_returned(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=42, recorder=rec).stream("file_layout")
        v = s.randbytes(4)
        (entry,) = rec.entries()
        assert entry.value == repr(v)
        # And the recorded string survives a pure-Python compare.
        assert isinstance(entry.value, str)


class TestShuffleIsExcluded:
    """RngStream deliberately does not expose shuffle.

    WHY: random.shuffle mutates in place and returns None. With value=repr(returned),
    every shuffle would record "None" regardless of the resulting permutation,
    defeating trace-driven divergence detection. Callers needing random
    reordering use sample(seq, k=len(seq)).
    """

    def test_shuffle_attribute_absent(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=1, recorder=rec).stream("a")
        assert not hasattr(s, "shuffle")


class TestRngStreamConstructionDoesNotLog:
    """Constructing RngStreams or asking for a stream records nothing.

    WHY: only user-facing draws should appear in the trace. If sub-seed
    derivation accidentally produced an entry, the trace would be polluted
    with non-deterministic counts depending on stream-cache lookups.
    """

    def test_constructor_does_not_record(self) -> None:
        rec = TraceRecorder()
        RngStreams(resolved_seed=42, recorder=rec)
        assert len(rec) == 0

    def test_stream_lookup_does_not_record(self) -> None:
        rec = TraceRecorder()
        streams = RngStreams(resolved_seed=42, recorder=rec)
        streams.stream("a")
        streams.stream("a")
        streams.stream("b")
        assert len(rec) == 0


class TestRngStreamSeparationByStream:
    """A single RngStreams produces independent sequences across streams.

    WHY: ensures the cache keys the underlying random.Random by name, not
    by accident of construction order.
    """

    def test_two_streams_under_one_factory_are_independent(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        a = streams.stream("a")
        b = streams.stream("b")
        a_draws = [a.random() for _ in range(10)]
        b_draws = [b.random() for _ in range(10)]
        # Same seed, different names — sub-seeds diverge.
        assert a_draws != b_draws


class TestStreamIsNotRandomSubclass:
    """RngStream is not a subclass of random.Random.

    WHY: subclassing leaks random.Random's undocumented internals (e.g.
    _randbelow) and creates a nested-recording problem when overridden
    methods call each other. The wrapper pattern is deliberate — see the
    Sprint 2 design spec rationale.
    """

    def test_not_a_random_subclass(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=42, recorder=rec).stream("a")
        assert not isinstance(s, random.Random)
        assert type(s) is RngStream
