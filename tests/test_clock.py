"""Tests for chaos_librarian.clock.parse_duration."""

from __future__ import annotations

import pytest

from chaos_librarian.clock import DurationParseError, parse_duration


class TestParseDurationValid:
    """Valid duration strings parse to the correct nanosecond count.

    WHY: validate and every downstream pass treats durations as i64 ns.
    """

    @pytest.mark.parametrize(
        ("raw", "expected_ns"),
        [
            ("0", 0),
            ("1ns", 1),
            ("500ns", 500),
            ("1us", 1_000),
            ("1ms", 1_000_000),
            ("500ms", 500_000_000),
            ("1s", 1_000_000_000),
            ("2s", 2_000_000_000),
            ("1m", 60_000_000_000),
            ("1m30s", 90_000_000_000),
            ("1h", 3_600_000_000_000),
            ("1h2m3s", 3_723_000_000_000),
            ("1h2m3s4ms5us6ns", 3_723_004_005_006),
        ],
    )
    def test_valid_durations(self, raw: str, expected_ns: int) -> None:
        assert parse_duration(raw) == expected_ns


class TestParseDurationRejected:
    """Each rejected form raises DurationParseError with a useful reason.

    WHY: scenario authors need to know why a duration was rejected so they
    can fix the YAML. Vague errors degrade the validate UX.
    """

    @pytest.mark.parametrize(
        ("raw", "reason_substr"),
        [
            ("", "empty"),
            (" ", "whitespace"),
            ("1", "missing unit"),
            ("s", "missing"),
            ("-1s", "negative"),
            ("1.5s", "fractional"),
            ("1y", "unknown unit"),
            ("1s1s", "duplicate unit"),
            ("1ms1s", "out of order"),
            ("1s 1ms", "whitespace"),
            ("9999999999h", "overflow"),
        ],
    )
    def test_rejected(self, raw: str, reason_substr: str) -> None:
        with pytest.raises(DurationParseError) as excinfo:
            parse_duration(raw)
        assert reason_substr in excinfo.value.reason
        assert excinfo.value.raw == raw


def test_overflow_exceeds_i64_max() -> None:
    """A duration whose total ns > 2**63 - 1 is rejected.

    WHY: silent overflow would corrupt the journal's logical_time_ns.
    """
    with pytest.raises(DurationParseError) as excinfo:
        parse_duration("10000000h")
    assert "overflow" in excinfo.value.reason
