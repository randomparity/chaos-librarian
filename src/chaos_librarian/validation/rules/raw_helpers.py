"""Raw validation-rule helpers and shared reporter types."""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, cast

from chaos_librarian.clock import DurationParseError, parse_duration
from chaos_librarian.contract.validation import ValidationSeverity

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.reporting import IssueCollector

_Loc = tuple[str | int, ...]
_RawMapping = Mapping[str, object]
Rule = Callable[[_RawMapping, "LineIndex", "IssueCollector"], None]


@dataclass(frozen=True, slots=True)
class Reporter:
    """Binds ``collector`` + ``line_index`` once per rule invocation.

    Replaces 5-kwarg ``collector.add(code=..., severity=...,
    message=..., loc=..., line_index=line_index)`` sites with 3-kwarg
    ``reporter.error(code=..., message=..., loc=...)``. Internal
    rule helpers thread one ``reporter`` arg instead of carrying
    ``collector`` and ``line_index`` separately.
    """

    collector: IssueCollector
    line_index: LineIndex

    def error(self, *, code: str, message: str, loc: _Loc) -> None:
        self.collector.add(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            loc=loc,
            line_index=self.line_index,
        )

    def warning(self, *, code: str, message: str, loc: _Loc) -> None:
        self.collector.add(
            code=code,
            severity=ValidationSeverity.WARNING,
            message=message,
            loc=loc,
            line_index=self.line_index,
        )


def _as_mapping(node: object) -> _RawMapping | None:
    """Narrow an ``object`` to ``Mapping[str, object]`` for safe ``.get`` calls.

    Returns None when ``node`` is non-mapping so the rule can skip the malformed
    sub-tree (Pydantic's shape pass owns the E_FIELD_TYPE report). ``cast`` is
    needed because ``isinstance`` against a generic alias is erased at runtime.
    """
    if isinstance(node, Mapping):
        return cast("_RawMapping", node)
    return None


def _as_list(node: object) -> list[object] | None:
    """Narrow an ``object`` to ``list[object]``; mirror of ``_as_mapping``."""
    if isinstance(node, list):
        return cast("list[object]", node)
    return None


def _str_or_default(node: object, default: str) -> str:
    if isinstance(node, str):
        return node
    return default


def _list_at_path(raw: _RawMapping, path_parts: tuple[str, ...]) -> list[object] | None:
    """Walk ``path_parts`` from ``raw`` and return the list at the end, or None."""
    node: object = raw
    for part in path_parts:
        parent = _as_mapping(node)
        if parent is None:
            return None
        node = parent.get(part)
    return _as_list(node)


def _iter_timeline_events(raw: _RawMapping) -> Iterator[tuple[int, _RawMapping]]:
    """Yield ``(idx, event)`` for each well-shaped event under ``raw["timeline"]``.

    Centralizes the iterate-and-narrow preamble every timeline-walking rule
    needs. Malformed events (non-mapping) are skipped silently — the shape
    pass already reported them.
    """
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        yield idx, event


def index_start_commit_events(
    events: Iterable[tuple[int, _RawMapping]],
    *,
    start_action: str,
    commit_action: str,
) -> tuple[dict[str, tuple[int, _RawMapping]], list[tuple[int, _RawMapping]]]:
    """Split timeline ``(idx, event)`` pairs into ``(starts_by_id, commits)``.

    Shared by the slow-copy and network-lag pairing rules: each indexes a start
    event by its ``id`` and collects the matching commit events, preserving the
    original timeline index for error ``loc`` reporting.
    """
    starts: dict[str, tuple[int, _RawMapping]] = {}
    commits: list[tuple[int, _RawMapping]] = []
    for idx, event in events:
        action = event.get("action")
        event_id = event.get("id")
        if action == start_action and isinstance(event_id, str):
            starts[event_id] = (idx, event)
        elif action == commit_action:
            commits.append((idx, event))
    return starts, commits


def report_unpaired_start(
    *,
    reporter: Reporter,
    code: str,
    start_noun: str,
    commit_noun: str,
    event_id: str,
    idx: int,
    matching_commit_count: int,
) -> None:
    """Emit a start/commit cardinality error unless the start has exactly one commit.

    No-op when ``matching_commit_count == 1``. Shared by the slow-copy and
    network-lag pairing rules, which use identical orphan/duplicate templates.
    """
    if matching_commit_count == 1:
        return
    if matching_commit_count == 0:
        message = f"{start_noun} {event_id!r} has no matching {commit_noun}"
    else:
        message = (
            f"{start_noun} {event_id!r} has {matching_commit_count} matching commits (expected 1)"
        )
    reporter.error(code=code, message=message, loc=("timeline", idx, "id"))


def first_or_duplicate[K, V](seen: dict[K, V], key: K, value: V) -> V | None:
    """Track first occurrences in ``seen`` for duplicate-detection rules.

    Returns the previously-stored value when ``key`` is a duplicate; otherwise
    records ``value`` and returns None. Callers own the per-rule duplicate
    message, error code, and severity.
    """
    if key in seen:
        return seen[key]
    seen[key] = value
    return None


def try_parse_duration(raw_str: str) -> int | None:
    """Parse a duration string; return None instead of raising.

    Rules that re-parse a duration string for arithmetic (5b: slow-copy
    timing, 7: timeline order) need to skip pairs where the input is
    malformed — Rule 3 has already flagged those with E_DURATION_SYNTAX,
    and re-reporting them as order/timing failures would be noise.
    """
    try:
        return parse_duration(raw_str)
    except DurationParseError:
        return None


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _enum[T: enum.StrEnum](enum_type: type[T], value: object) -> T | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None
