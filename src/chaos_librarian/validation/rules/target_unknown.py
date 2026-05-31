"""Rules 4 + 12: closed-set identifier checks.

``rule_target_unknown`` (E_TARGET_UNKNOWN) rejects timeline target references
that don't resolve to the entity kind required by the action. ``rule_root_unknown``
(E_ROOT_UNKNOWN) rejects ``move_between_roots`` events that reference
unknown ``from_root_id`` / ``to_root_id`` values and rejects
``library.archive_root`` values that don't match any declared root id
(sentinel ``"archive"`` and ``None`` are both valid).

Both rules validate closed-set identifier references — keeping them
in one module keeps the helper imports and the "declared-id walk"
pattern together.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_ROOT_UNKNOWN, E_TARGET_UNKNOWN
from chaos_librarian.validation.rules.hierarchy_walkers import (
    entity_ids_by_kind,
    iter_declared_roots,
)
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_root_unknown", "rule_target_unknown"]


_ASSET_TARGET_ACTIONS: frozenset[str] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
        TimelineActionName.ADD_FILE,
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.SLOW_COPY_START,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        TimelineActionName.CORRUPT_TAGS,
        TimelineActionName.TOUCH_MTIME,
        TimelineActionName.WRONG_ORACLE_HASH,
        TimelineActionName.NETWORK_LAG_START,
        TimelineActionName.SIMULATE_QUOTA_EXCEEDED,
        TimelineActionName.SIMULATE_STALE_HANDLE,
        TimelineActionName.ACQUIRE_LOCK,
    }
)

_HIERARCHY_TARGET_KIND_BY_ACTION: dict[str, str] = {
    TimelineActionName.RENUMBER_EPISODE: "episode",
    TimelineActionName.MOVE_EPISODE_TO_SEASON: "episode",
    TimelineActionName.RENAME_SEASON: "season",
    TimelineActionName.RENUMBER_DISC: "disc",
    TimelineActionName.MOVE_TRACK_TO_DISC: "track",
    TimelineActionName.SWAP_EPISODE_NUMBERS: "episode",
    TimelineActionName.SWAP_DISC_NUMBERS: "disc",
    TimelineActionName.SWAP_TRACK_NUMBERS: "track",
    TimelineActionName.REPUBLISH_EPISODE: "podcast_episode",
    TimelineActionName.MARK_EPISODE_STALE: "podcast_episode",
}

# Each swap action's second-operand field and the entity kind it must resolve to.
# Resolving against the kind's own disjoint id set means a declared id of the wrong
# kind (e.g. a season id in ``with_episode``) yields E_TARGET_UNKNOWN, not
# E_HIERARCHY_INVALID.
_SWAP_WITH_FIELD_BY_ACTION: dict[str, tuple[str, str]] = {
    TimelineActionName.SWAP_EPISODE_NUMBERS: ("with_episode", "episode"),
    TimelineActionName.SWAP_DISC_NUMBERS: ("with_disc", "disc"),
    TimelineActionName.SWAP_TRACK_NUMBERS: ("with_track", "track"),
}


def rule_target_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject timeline events whose references do not resolve by action kind.

    Events with no string ``target`` (e.g. ``slow_copy_commit``) are
    skipped: Pydantic's shape pass owns "the field must exist."
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    entity_ids = entity_ids_by_kind(raw)
    for idx, event in _iter_timeline_events(raw):
        _check_target_reference(event, idx, entity_ids, reporter)
        _check_destination_reference(event, idx, entity_ids, reporter)


def _check_target_reference(
    event: Mapping[str, object],
    idx: int,
    entity_ids: dict[str, set[str]],
    reporter: Reporter,
) -> None:
    action = event.get("action")
    target_kind = _target_kind_for_action(action)
    if target_kind is None:
        return

    target = event.get("target")
    if not isinstance(target, str):
        return
    if target not in entity_ids[target_kind]:
        reporter.error(
            code=E_TARGET_UNKNOWN,
            message=f"target {target_kind} {target!r} is not defined",
            loc=("timeline", idx, "target"),
        )


def _target_kind_for_action(action: object) -> str | None:
    if action in _ASSET_TARGET_ACTIONS:
        return "asset"
    if isinstance(action, str):
        return _HIERARCHY_TARGET_KIND_BY_ACTION.get(action)
    return None


def _check_destination_reference(
    event: Mapping[str, object],
    idx: int,
    entity_ids: dict[str, set[str]],
    reporter: Reporter,
) -> None:
    action = event.get("action")
    if action == TimelineActionName.MOVE_EPISODE_TO_SEASON:
        _check_field_reference(
            event,
            idx,
            field="to_season",
            target_kind="season",
            entity_ids=entity_ids,
            reporter=reporter,
        )
    elif action == TimelineActionName.MOVE_TRACK_TO_DISC:
        _check_field_reference(
            event,
            idx,
            field="to_disc",
            target_kind="disc",
            entity_ids=entity_ids,
            reporter=reporter,
        )
    elif isinstance(action, str) and action in _SWAP_WITH_FIELD_BY_ACTION:
        field, target_kind = _SWAP_WITH_FIELD_BY_ACTION[action]
        _check_field_reference(
            event,
            idx,
            field=field,
            target_kind=target_kind,
            entity_ids=entity_ids,
            reporter=reporter,
        )


def _check_field_reference(
    event: Mapping[str, object],
    idx: int,
    *,
    field: str,
    target_kind: str,
    entity_ids: dict[str, set[str]],
    reporter: Reporter,
) -> None:
    value = event.get(field)
    if not isinstance(value, str):
        return
    if value not in entity_ids[target_kind]:
        reporter.error(
            code=E_TARGET_UNKNOWN,
            message=f"{field} {value!r} is not a declared {target_kind} id",
            loc=("timeline", idx, field),
        )


def rule_root_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject move_between_roots / archive_root referencing unknown roots.

    The closed set of valid root ids is ``library.roots[].id`` plus the
    sentinel ``"archive"`` (only for ``library.archive_root``). Non-string
    or absent values are skipped — Pydantic's shape pass owns shape errors.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    library = _as_mapping(raw.get("library"))
    if library is None:
        return  # Pydantic owns shape
    declared_ids = {root_id for root_id, _ in iter_declared_roots(raw)}

    archive_root = library.get("archive_root")
    if (
        isinstance(archive_root, str)
        and archive_root != "archive"
        and archive_root not in declared_ids
    ):
        reporter.error(
            code=E_ROOT_UNKNOWN,
            message=f"library.archive_root {archive_root!r} is not a declared root id",
            loc=("library", "archive_root"),
        )

    _check_move_between_roots(raw, declared_ids, reporter)


def _check_move_between_roots(
    raw: Mapping[str, object],
    declared_ids: set[str],
    reporter: Reporter,
) -> None:
    """Emit E_ROOT_UNKNOWN for each move_between_roots field outside ``declared_ids``."""
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.MOVE_BETWEEN_ROOTS:
            continue
        for field in ("from_root_id", "to_root_id"):
            value = event.get(field)
            if not isinstance(value, str):
                continue  # Pydantic owns shape
            if value not in declared_ids:
                reporter.error(
                    code=E_ROOT_UNKNOWN,
                    message=f"{field} {value!r} is not a declared root id",
                    loc=("timeline", idx, field),
                )
