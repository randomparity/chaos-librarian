"""Deterministic wall-clock scheduling helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from chaos_librarian.errors import ChaosLibrarianValueError


class SpeedParseError(ChaosLibrarianValueError):
    """Raised when ``--speed`` is not a positive decimal multiplier."""


@dataclass(frozen=True, slots=True)
class SpeedMultiplier:
    """Exact rational form of a parsed speed multiplier."""

    numerator: int
    denominator: int
    normalized: str


def parse_speed(raw: str) -> SpeedMultiplier:
    """Parse a speed string like ``10x`` or ``0.5x`` into exact integer math."""
    if not raw.endswith("x"):
        raise SpeedParseError(f"invalid speed {raw!r}: missing x suffix")
    body = raw[:-1]
    try:
        value = Decimal(body)
    except InvalidOperation as exc:
        raise SpeedParseError(f"invalid speed {raw!r}: not decimal") from exc
    if not value.is_finite():
        raise SpeedParseError(f"invalid speed {raw!r}: must be finite")
    if value <= 0:
        raise SpeedParseError(f"invalid speed {raw!r}: must be greater than zero")
    fraction = Fraction(value)
    normalized = format(value.normalize(), "f").rstrip("0").rstrip(".")
    return SpeedMultiplier(fraction.numerator, fraction.denominator, normalized)


def logical_now_ns(elapsed_wall_ns: int, speed: SpeedMultiplier) -> int:
    """Convert wall-clock elapsed ns to logical scenario ns using floor division."""
    return elapsed_wall_ns * speed.numerator // speed.denominator


def due_event_count(
    logical_times_ns: Sequence[int],
    *,
    logical_ns: int,
    cursor: int,
) -> int:
    """Count due entries at or after ``cursor`` without scanning past the first future time."""
    count = 0
    for at_ns in logical_times_ns[cursor:]:
        if at_ns > logical_ns:
            break
        count += 1
    return count
