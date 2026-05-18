"""Duration-string parser shared by validate, plan, and run.

Grammar matches docs/specs/chaos-librarian-design.md §"Time Model":
``<int><unit>`` segments in strictly descending order, units in
``h / m / s / ms / us / ns``, bare ``"0"`` accepted, no spaces, no fractions,
no negatives. Result is i64 nanoseconds.
"""

from __future__ import annotations

import re
from typing import Final, NoReturn

from chaos_librarian.errors import ChaosLibrarianError

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

_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"(?P<n>\d+)(?P<u>[a-z]+)")

_VALID_UNITS: Final[tuple[str, ...]] = tuple(u for u, _ in _UNITS_DESCENDING)


class DurationParseError(ChaosLibrarianError):
    """Raised when a duration string violates the grammar or overflows i64."""

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"invalid duration {raw!r}: {reason}")
        self.raw = raw
        self.reason = reason


def _reject_obvious(raw: str) -> None:
    """Reject inputs that fail before regex matching even helps."""
    if not raw:
        raise DurationParseError(raw, "empty string")
    if raw.startswith("-"):
        raise DurationParseError(raw, "negative durations not allowed")
    if any(c.isspace() for c in raw):
        raise DurationParseError(raw, "whitespace not allowed")
    if "." in raw:
        raise DurationParseError(raw, "fractional durations not allowed")


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
    _reject_obvious(raw)
    if raw == "0":
        return 0

    match = _DURATION_RE.fullmatch(raw)
    if match is None:
        if raw.isdigit():
            raise DurationParseError(raw, "missing unit suffix")
        _raise_diagnostic(raw)

    groups = match.groupdict()
    if all(v is None for v in groups.values()):
        raise DurationParseError(raw, "missing unit suffix")
    return _accumulate_ns(raw, groups)


def _accumulate_ns(raw: str, groups: dict[str, str | None]) -> int:
    """Sum the captured per-unit segments into i64 nanoseconds.

    Raises:
        DurationParseError: When the running total exceeds ``_I64_MAX_NS``.
    """
    total = 0
    for unit, multiplier in _UNITS_DESCENDING:
        captured = groups[unit]
        if captured is None:
            continue
        total += int(captured) * multiplier
        if total > _I64_MAX_NS:
            raise DurationParseError(raw, "overflow (exceeds i64 nanoseconds)")
    return total


def _raise_diagnostic(raw: str) -> NoReturn:
    """Always raises with a precise reason for inputs the canonical regex rejects.

    The loop is exhaustive: every position either raises a specific error or
    consumes a valid ``\\d+[unit]+`` segment whose unit is checked against
    ``_VALID_UNITS`` and against the descending-order / no-duplicates rules.
    Any input where every segment is valid and ordered would have matched
    ``_DURATION_RE`` in the first place, so control should never fall through
    the loop. The post-loop ``raise`` is required for ``ty`` to honor the
    ``NoReturn`` annotation; reaching it would mean ``_DURATION_RE`` and this
    diagnostic disagree on what a valid duration looks like.
    """
    seen_unit_indices: list[int] = []
    pos = 0
    while pos < len(raw):
        m = _SEGMENT_RE.match(raw, pos)
        if m is None:
            if raw[pos].isalpha():
                raise DurationParseError(raw, "missing numeric value before unit")
            raise DurationParseError(raw, f"unexpected character at offset {pos}")
        unit = m.group("u")
        if unit not in _VALID_UNITS:
            raise DurationParseError(raw, f"unknown unit {unit!r}")
        idx = _VALID_UNITS.index(unit)
        if idx in seen_unit_indices:
            raise DurationParseError(raw, f"duplicate unit {unit!r}")
        if seen_unit_indices and idx < seen_unit_indices[-1]:
            raise DurationParseError(raw, "units out of order (must be descending)")
        seen_unit_indices.append(idx)
        pos = m.end()
    raise DurationParseError(raw, "does not match duration grammar")  # pragma: no cover
