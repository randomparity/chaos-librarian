"""Tests for deterministic wall-clock scheduler math."""

from __future__ import annotations

import pytest

from chaos_librarian.materializer.scheduler import (
    SpeedParseError,
    due_event_count,
    logical_now_ns,
    parse_speed,
)


def test_parse_speed_normalizes_decimal() -> None:
    speed = parse_speed("0.50x")
    assert speed.numerator == 1
    assert speed.denominator == 2
    assert speed.normalized == "0.5"


def test_parse_speed_rejects_invalid() -> None:
    for raw in ("", "0x", "-1x", "1", "x", "1..0x"):
        with pytest.raises(SpeedParseError):
            parse_speed(raw)


def test_logical_now_uses_floor_arithmetic() -> None:
    assert logical_now_ns(1, parse_speed("0.5x")) == 0
    assert logical_now_ns(3, parse_speed("0.5x")) == 1


def test_due_event_count_counts_prefix_only() -> None:
    assert due_event_count([10, 20, 20, 30], logical_ns=20, cursor=0) == 3
    assert due_event_count([10, 20, 20, 30], logical_ns=20, cursor=2) == 1
