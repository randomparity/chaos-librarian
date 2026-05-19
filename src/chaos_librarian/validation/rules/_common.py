"""Shared types and raw-data narrowing helpers for ``validation/rules/``.

Every rule module in this subpackage imports the ``Rule`` callable type
and the ``_as_*`` / ``_list_at_path`` / ``_iter_timeline_events`` helpers
from here. ``IssueCollector`` and ``LineIndex`` are kept behind
``TYPE_CHECKING`` because importing them at runtime would re-introduce
the ``pipeline → semantic → rules → pipeline`` import cycle that the
package layout is designed to avoid.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = [
    "Rule",
    "_Loc",
    "_RawMapping",
    "_as_list",
    "_as_mapping",
    "_iter_timeline_events",
    "_list_at_path",
]


_Loc = tuple[str | int, ...]
_RawMapping = Mapping[str, object]
Rule = Callable[[_RawMapping, "LineIndex", "IssueCollector"], None]


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
