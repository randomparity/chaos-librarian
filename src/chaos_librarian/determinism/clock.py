"""Logical clock and duration formatters.

The Clock is monotonic-only — no scheduling, no wall-clock awareness.
Sprint 3 will use it to walk a timeline's ``at:`` values; Sprint 8 will
add wall-clock-mode wiring on top.

The formatters here pair with Sprint 1's
``chaos_librarian.clock.parse_duration``. The round-trip identity
``parse_duration(format_duration_human(ns)) == ns`` holds for every
``ns >= 0`` representable as a clean h/m/s/ms sum (no microsecond /
nanosecond residue).
"""

from __future__ import annotations

from dataclasses import dataclass

_NS_PER_HOUR = 3_600_000_000_000
_NS_PER_MINUTE = 60_000_000_000
_NS_PER_SECOND = 1_000_000_000
_NS_PER_MS = 1_000_000
_NS_PER_US = 1_000

_HUMAN_UNITS: tuple[tuple[str, int], ...] = (
    ("h", _NS_PER_HOUR),
    ("m", _NS_PER_MINUTE),
    ("s", _NS_PER_SECOND),
    ("ms", _NS_PER_MS),
    ("us", _NS_PER_US),
    ("ns", 1),
)


@dataclass
class Clock:
    """Monotonic logical clock measured in nanoseconds since t=0."""

    current_ns: int = 0

    def advance(self, delta_ns: int) -> int:
        """Move the clock forward by ``delta_ns`` and return the new ``current_ns``.

        Raises:
            ValueError: If ``delta_ns < 0``.
        """
        if delta_ns < 0:
            raise ValueError(f"advance requires delta_ns >= 0, got {delta_ns}")
        self.current_ns += delta_ns
        return self.current_ns

    def now(self) -> int:
        """Return the current logical timestamp in nanoseconds."""
        return self.current_ns

    def set_to(self, target_ns: int) -> None:
        """Jump the clock to ``target_ns``.

        Raises:
            ValueError: If ``target_ns`` is earlier than ``current_ns``.
        """
        if target_ns < self.current_ns:
            raise ValueError(
                f"set_to requires target_ns >= current_ns ({self.current_ns}), got {target_ns}"
            )
        self.current_ns = target_ns


def format_duration_human(ns: int) -> str:
    """Format ``ns`` as a grammar-compatible duration string.

    Examples:
        ``format_duration_human(0) == "0s"``
        ``format_duration_human(90_250_000_000) == "1m30s250ms"``
        ``format_duration_human(90_250_500_123) == "1m30s250ms500us123ns"``

    The output is parseable by ``chaos_librarian.clock.parse_duration``
    when the input has no sub-millisecond residue.

    Raises:
        ValueError: If ``ns < 0``.
    """
    if ns < 0:
        raise ValueError(f"format_duration_human requires ns >= 0, got {ns}")
    if ns == 0:
        return "0s"
    parts: list[str] = []
    remaining = ns
    for unit, multiplier in _HUMAN_UNITS:
        count, remaining = divmod(remaining, multiplier)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


def format_duration_json(ns: int) -> int:
    """Return ``ns`` verbatim after a type check.

    Exists as a named function so every JSON emission site is grep-able
    and can be swapped to a string representation later without touching
    call sites.

    Raises:
        TypeError: If ``ns`` is not an ``int``.
    """
    if not isinstance(ns, int):
        raise TypeError(f"format_duration_json expects int, got {type(ns).__name__}")
    return ns
