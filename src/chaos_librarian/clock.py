"""Duration-string parser shared by validate, plan, and run.

Grammar matches docs/specs/chaos-librarian-design.md §"Time Model":
``<int><unit>`` segments in strictly descending order, units in
``h / m / s / ms / us / ns``, bare ``"0"`` accepted, no spaces, no fractions,
no negatives. Result is i64 nanoseconds.
"""

from __future__ import annotations

import re
from typing import Final

_I64_MAX_NS: Final[int] = 2**63 - 1

_UNITS_DESCENDING: Final[tuple[tuple[str, int], ...]] = (
    ("h", 3_600_000_000_000),
    ("m", 60_000_000_000),
    ("s", 1_000_000_000),
    ("ms", 1_000_000),
    ("us", 1_000),
    ("ns", 1),
)

_DURATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\A"
    r"(?:(?P<h>\d+)h)?"
    r"(?:(?P<m>\d+)m)?"
    r"(?:(?P<s>\d+)s)?"
    r"(?:(?P<ms>\d+)ms)?"
    r"(?:(?P<us>\d+)us)?"
    r"(?:(?P<ns>\d+)ns)?"
    r"\Z"
)


class DurationParseError(ValueError):
    """Raised when a duration string violates the grammar or overflows i64."""

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"invalid duration {raw!r}: {reason}")
        self.raw = raw
        self.reason = reason


def parse_duration(raw: str) -> int:
    """Parse a duration string into integer nanoseconds.

    Args:
        raw: Duration string like ``"500ms"``, ``"2s"``, ``"1m30s"``, ``"0"``.

    Returns:
        Non-negative integer nanoseconds (i64 range).

    Raises:
        DurationParseError: For any rejection mode (see grammar in module
            docstring). The exception's ``reason`` field carries a short
            human-readable description.
    """
    if not raw:
        raise DurationParseError(raw, "empty string")
    if raw[0] == "-":
        raise DurationParseError(raw, "negative durations not allowed")
    if any(c.isspace() for c in raw):
        raise DurationParseError(raw, "whitespace not allowed")
    if "." in raw:
        raise DurationParseError(raw, "fractional durations not allowed")
    if raw == "0":
        return 0

    match = _DURATION_RE.fullmatch(raw)
    if match is None:
        if raw.isdigit():
            raise DurationParseError(raw, "missing unit suffix")
        _diagnose_or_raise(raw)
        raise DurationParseError(raw, "does not match duration grammar")

    groups = match.groupdict()
    if all(v is None for v in groups.values()):
        raise DurationParseError(raw, "missing unit suffix")

    total = 0
    for unit, multiplier in _UNITS_DESCENDING:
        captured = groups.get(unit)
        if captured is None:
            continue
        try:
            value = int(captured)
        except ValueError as e:  # pragma: no cover — regex guarantees digits
            raise DurationParseError(raw, f"non-integer segment {captured!r}") from e
        total += value * multiplier
        if total > _I64_MAX_NS:
            raise DurationParseError(raw, "overflow (exceeds i64 nanoseconds)")
    return total


def _diagnose_or_raise(raw: str) -> None:
    """Produce a precise reason for inputs the canonical regex rejects."""
    seen_unit_indices: list[int] = []
    pos = 0
    segment_re = re.compile(r"(?P<n>\d+)(?P<u>[a-z]+)")
    valid_units = [u for u, _ in _UNITS_DESCENDING]
    while pos < len(raw):
        m = segment_re.match(raw, pos)
        if m is None:
            if raw[pos].isalpha():
                raise DurationParseError(raw, "missing numeric value before unit")
            raise DurationParseError(raw, f"unexpected character at offset {pos}")
        unit = m.group("u")
        if unit not in valid_units:
            raise DurationParseError(raw, f"unknown unit {unit!r}")
        idx = valid_units.index(unit)
        if idx in seen_unit_indices:
            raise DurationParseError(raw, f"duplicate unit {unit!r}")
        if seen_unit_indices and idx < seen_unit_indices[-1]:
            raise DurationParseError(raw, "units out of order (must be descending)")
        seen_unit_indices.append(idx)
        pos = m.end()
