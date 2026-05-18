"""Property tests for RngStreams stream independence."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chaos_librarian.determinism.rng import RngStreams
from chaos_librarian.determinism.trace import TraceRecorder


@given(
    seed=st.integers(min_value=0, max_value=2**63 - 1),
    a_draws=st.integers(min_value=0, max_value=64),
    b_draws=st.integers(min_value=1, max_value=32),
)
@settings(max_examples=200, deadline=None)
def test_stream_b_draws_are_independent_of_stream_a(seed: int, a_draws: int, b_draws: int) -> None:
    """Drawing from stream A any number of times does not perturb stream B.

    WHY: this is the operational form of the "stream independence"
    determinism guarantee — Sprint 5/6/7 add new stream names without
    invalidating earlier fixtures because each sub-seed is derived
    independently from sha256(seed/name).
    """
    rec_with_a = TraceRecorder()
    streams_with_a = RngStreams(resolved_seed=seed, recorder=rec_with_a)
    stream_a = streams_with_a.stream("a")
    for _ in range(a_draws):
        stream_a.random()
    stream_b = streams_with_a.stream("b")
    with_a = [stream_b.random() for _ in range(b_draws)]

    rec_without_a = TraceRecorder()
    streams_without_a = RngStreams(resolved_seed=seed, recorder=rec_without_a)
    stream_b_solo = streams_without_a.stream("b")
    without_a = [stream_b_solo.random() for _ in range(b_draws)]

    assert with_a == without_a
