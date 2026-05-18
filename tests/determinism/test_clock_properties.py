"""Property tests for the parse_duration / format_duration_human round-trip."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chaos_librarian.clock import parse_duration
from chaos_librarian.determinism.clock import format_duration_human

_NS_PER_HOUR = 3_600_000_000_000
_NS_PER_MINUTE = 60_000_000_000
_NS_PER_SECOND = 1_000_000_000
_NS_PER_MS = 1_000_000


@given(
    hours=st.integers(min_value=0, max_value=23),
    minutes=st.integers(min_value=0, max_value=59),
    seconds=st.integers(min_value=0, max_value=59),
    millis=st.integers(min_value=0, max_value=999),
)
@settings(max_examples=200, deadline=None)
def test_parse_format_round_trip_over_clean_hms_ms_sum(
    hours: int, minutes: int, seconds: int, millis: int
) -> None:
    """parse_duration(format_duration_human(ns)) == ns for any clean h/m/s/ms sum.

    WHY: round-trip stability is a load-bearing determinism guarantee —
    Sprint 3 formats durations into bundles, and Sprint 4's replay may
    re-parse them. The strategy bounds keep the composed sum well below
    i64_max, so overflow is impossible here.
    """
    ns = (
        hours * _NS_PER_HOUR
        + minutes * _NS_PER_MINUTE
        + seconds * _NS_PER_SECOND
        + millis * _NS_PER_MS
    )
    assert parse_duration(format_duration_human(ns)) == ns
