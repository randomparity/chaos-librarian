"""Tests for chaos_librarian.determinism.clock."""

from __future__ import annotations

import pytest

from chaos_librarian.clock import parse_duration
from chaos_librarian.determinism.clock import (
    Clock,
    format_duration_human,
    format_duration_json,
)


class TestClockMonotonic:
    """Clock only moves forward.

    WHY: Sprint 3 walks a timeline by issuing set_to(at:) jumps; any backward
    motion would silently reorder events that the journal must record in
    declared order.
    """

    def test_default_starts_at_zero(self) -> None:
        assert Clock().now() == 0

    def test_advance_returns_new_now(self) -> None:
        clk = Clock()
        new_now = clk.advance(1_000)
        assert new_now == 1_000
        assert clk.now() == 1_000

    def test_advance_accumulates(self) -> None:
        clk = Clock()
        clk.advance(500)
        clk.advance(250)
        assert clk.now() == 750

    def test_advance_zero_is_ok(self) -> None:
        clk = Clock()
        assert clk.advance(0) == 0

    def test_advance_negative_raises(self) -> None:
        clk = Clock()
        with pytest.raises(ValueError, match="delta_ns"):
            clk.advance(-1)

    def test_set_to_forward_is_ok(self) -> None:
        clk = Clock()
        clk.set_to(5_000)
        assert clk.now() == 5_000
        clk.set_to(5_000)
        assert clk.now() == 5_000

    def test_set_to_backward_raises(self) -> None:
        clk = Clock()
        clk.set_to(5_000)
        with pytest.raises(ValueError, match="current_ns"):
            clk.set_to(4_999)

    def test_negative_initial_value_raises(self) -> None:
        # WHY: direct construction bypasses advance/set_to guards; a negative
        # initial clock would silently corrupt every downstream timestamp.
        with pytest.raises(ValueError, match="current_ns"):
            Clock(current_ns=-1)


class TestFormatDurationHumanEdges:
    """Edge cases for format_duration_human.

    WHY: every JSON-vs-human boundary in later sprints calls this; surprising
    output here ripples into log readability and into the parse/format
    round-trip guarantee.
    """

    def test_zero(self) -> None:
        assert format_duration_human(0) == "0s"

    def test_minute_and_milliseconds(self) -> None:
        # The canonical example from the design spec.
        assert format_duration_human(90_250_000_000) == "1m30s250ms"

    def test_microsecond_residue(self) -> None:
        # 1m30s250ms + 500us, exactly the spec example.
        assert format_duration_human(90_250_000_000 + 500_000) == "1m30s250ms500us"

    def test_nanosecond_residue(self) -> None:
        assert format_duration_human(90_250_000_000 + 500_000 + 123) == "1m30s250ms500us123ns"

    def test_only_top_unit(self) -> None:
        assert format_duration_human(1_000_000_000) == "1s"
        assert format_duration_human(60_000_000_000) == "1m"
        assert format_duration_human(3_600_000_000_000) == "1h"

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            format_duration_human(-1)

    def test_bool_raises_type_error(self) -> None:
        # WHY: bool is a subclass of int, so isinstance(True, int) is True;
        # without an explicit guard, format_duration_human(True) returns "1ns"
        # which is a silent footgun at call sites that pass untrusted input.
        with pytest.raises(TypeError):
            format_duration_human(True)


class TestFormatDurationJson:
    """format_duration_json returns ints verbatim.

    WHY: the function exists as a named hop so every JSON emission site is
    grep-able and can be swapped to a string representation later without
    touching call sites.
    """

    def test_returns_int_verbatim(self) -> None:
        assert format_duration_json(0) == 0
        assert format_duration_json(90_250_000_000) == 90_250_000_000

    def test_non_int_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            format_duration_json("90s")  # ty: ignore[invalid-argument-type]

    def test_bool_raises_type_error(self) -> None:
        # WHY: bool is a subclass of int; without an explicit guard,
        # format_duration_json(True) returns True (not 1), which breaks
        # downstream JSON consumers expecting a plain integer.
        with pytest.raises(TypeError):
            format_duration_json(True)


class TestParseFormatRoundTripExamples:
    """Hand-rolled spot checks before the hypothesis property in Task 7.

    WHY: the round-trip property is load-bearing — Sprint 3 will format
    durations into bundles and Sprint 4 may re-parse them on replay.
    """

    @pytest.mark.parametrize(
        "ns",
        [
            0,
            1_000_000,  # 1ms
            500_000_000,  # 500ms
            1_000_000_000,  # 1s
            90_250_000_000,  # 1m30s250ms
            3_723_000_000_000,  # 1h2m3s
        ],
    )
    def test_round_trip(self, ns: int) -> None:
        assert parse_duration(format_duration_human(ns)) == ns
