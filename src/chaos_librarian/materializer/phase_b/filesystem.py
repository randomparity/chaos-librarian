"""Phase-B disk effects for materialize mode (Sprint 6+).

The dispatcher walks the engine-produced journal and applies real
filesystem effects against ``<run-dir>/library/``. Composition is
strictly one-directional: this module imports engine + contract but
no engine module imports back.

``FilesystemPhaseBContext`` carries three pieces of incremental state alongside
the walk: ``pending_slow_copy`` (start->commit bookkeeping),
``phase_b_sidecar_hashes`` (drained after the walk by
``manifest_build.augment_timeline_sidecars``), and a read-only
``scenario_assets`` lookup for metadata. Each per-action helper reads
its source path from ``entry.state_delta`` -- the journal is the truth
source -- so there is no cached path-tracking map.

Raises ``FilesystemActionError`` on the first handler exception (any
``Exception``, not just ``OSError``) so the orchestrator can route
through ``cleanup_failed_run``.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.contract.paths import resolve_under_library
from chaos_librarian.contract.scenario import (
    HIERARCHY_TIMELINE_ACTIONS,
    Asset,
    TimelineActionName,
)
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.phase_b.content import hash_file

__all__ = [
    "FilesystemPhaseBContext",
    "apply_filesystem_action",
    "make_filesystem_phase_b_context",
    "promote_slow_copy",
    "supports_filesystem_action",
]


@dataclass(frozen=True, slots=True)
class _PendingSlowCopy:
    asset_id: str
    initial_path: str
    temp_path: str


@dataclass(slots=True)
class FilesystemPhaseBContext:
    library_root: Path
    scenario_assets: Mapping[str, Asset]
    resolved_seed: int
    pending_slow_copy: dict[str, _PendingSlowCopy] = field(default_factory=dict)
    phase_b_sidecar_hashes: dict[str, str] = field(default_factory=dict)
    restoration_cache: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _HierarchyMove:
    asset_id: str
    from_path: str
    to_path: str


@dataclass(frozen=True, slots=True)
class _PlannedHierarchyMove:
    move: _HierarchyMove
    source: Path
    destination: Path
    temp: Path


_UNSAFE_HIERARCHY_TEMP_TOKEN_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")
_HIERARCHY_TEMP_TOKEN_PREFIX_LENGTH: Final = 48
_HIERARCHY_TEMP_PATH_ATTEMPTS: Final = 100


def make_filesystem_phase_b_context(
    *,
    library_root: Path,
    scenario_assets: Mapping[str, Asset],
    resolved_seed: int,
) -> FilesystemPhaseBContext:
    return FilesystemPhaseBContext(
        library_root=library_root,
        scenario_assets=scenario_assets,
        resolved_seed=resolved_seed,
    )


def supports_filesystem_action(action: TimelineActionName) -> bool:
    return action in _DISPATCH


def apply_filesystem_action(
    ctx: FilesystemPhaseBContext, entry: JournalEntry
) -> FilesystemAction | None:
    """Dispatch one journal entry to its helper; fill ``duration_ns``.

    Returns ``None`` if the action is not a filesystem effect.
    """
    action = TimelineActionName(entry.action)
    handler = _DISPATCH.get(action)
    if handler is None:
        return None
    started = time.monotonic_ns()
    try:
        result = handler(ctx, entry)
    except Exception as exc:
        # Widened from OSError so contract-drift bugs (e.g. KeyError from a
        # handler reading scenario_assets, or _slow_copy_commit's
        # non-committed-entry guard) still route through cleanup + exit 5
        # instead of escaping the dispatcher unwrapped.
        target_asset = _filesystem_error_asset_id(action, entry)
        raise FilesystemActionError(
            f"{entry.action} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id,
            cause=exc,
            action=action,
            asset_id=target_asset,
        ) from exc
    if result is None:
        return None
    return result.model_copy(update={"duration_ns": time.monotonic_ns() - started})


def _filesystem_error_asset_id(action: TimelineActionName, entry: JournalEntry) -> str | None:
    if action in _HIERARCHY_ACTIONS:
        return _first_hierarchy_move_asset_id(entry)
    return entry.target_ids[0] if entry.target_ids else None


def _first_hierarchy_move_asset_id(entry: JournalEntry) -> str | None:
    try:
        moves = _normalize_hierarchy_moves(entry)
    except Exception:
        return None
    if not moves:
        return None
    return moves[0].asset_id


def _move_asset(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Move a file in-place.

    Shared body for ``move_asset`` / ``rename_file`` / ``archive_file`` /
    ``move_between_roots``. All four emit ``from_path`` + ``to_path`` in
    ``state_delta``; the action discriminator on the returned
    ``FilesystemAction`` is taken from ``entry.action`` so consumers can
    distinguish the four cases without re-reading the scenario.
    """
    asset_id = entry.target_ids[0]
    from_path = str(entry.state_delta["from_path"])
    to_path = str(entry.state_delta["to_path"])
    src = ctx.library_root / from_path
    dst = ctx.library_root / to_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName(entry.action),
        target_asset_id=asset_id,
        from_path=from_path,
        to_path=to_path,
        temp_path=None,
        duration_ns=0,
    )


def _delete_file(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Unlink the file at ``state_delta['removed_path']``."""
    asset_id = entry.target_ids[0]
    removed_path = str(entry.state_delta["removed_path"])
    removed = ctx.library_root / removed_path
    ctx.restoration_cache[asset_id] = removed.read_bytes()
    removed.unlink()
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.DELETE_FILE,
        target_asset_id=asset_id,
        from_path=removed_path,
        to_path=None,
        temp_path=None,
        duration_ns=0,
    )


def _add_file(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Restore bytes removed by an earlier ``delete_file`` event."""
    asset_id = entry.target_ids[0]
    added_path = str(entry.state_delta["added_path"])
    data = ctx.restoration_cache.pop(asset_id)
    dst = ctx.library_root / added_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.ADD_FILE,
        target_asset_id=asset_id,
        from_path=None,
        to_path=added_path,
        temp_path=None,
        duration_ns=0,
    )


def _remove_sidecar(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Unlink the sidecar at ``state_delta['removed_sidecar_path']``.

    Routed through phase B (not media.py) because there is no ffmpeg
    work -- the manifest sidecar row is removed by the engine, the file
    is removed here. Mirrors ``_delete_file``'s shape so consumers can
    read ``from_path`` for the removed path and treat ``to_path=None``
    as the audit-log signal that the inode is gone.
    """
    asset_id = entry.target_ids[0]
    removed_path = str(entry.state_delta["removed_sidecar_path"])
    (ctx.library_root / removed_path).unlink()
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.REMOVE_SIDECAR,
        target_asset_id=asset_id,
        from_path=removed_path,
        to_path=None,
        temp_path=None,
        duration_ns=0,
    )


def _touch_mtime(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Adjust file mtime without changing content bytes."""
    asset_id = entry.target_ids[0]
    path = str(entry.state_delta["path"])
    target = resolve_under_library(Path(path), ctx.library_root)
    offset_ns = parse_duration(str(entry.state_delta["offset"]))
    content_hash = hash_file(target)
    before = target.stat()
    mtime_after_ns = before.st_mtime_ns + offset_ns
    os.utime(target, ns=(before.st_atime_ns, mtime_after_ns))
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.TOUCH_MTIME,
        target_asset_id=asset_id,
        from_path=path,
        to_path=path,
        temp_path=None,
        content_hash=content_hash,
        mtime_before_ns=before.st_mtime_ns,
        mtime_after_ns=mtime_after_ns,
        duration_ns=0,
    )


def _hierarchy_moves(
    ctx: FilesystemPhaseBContext,
    entry: JournalEntry,
) -> FilesystemAction | None:
    """Apply engine-rendered hierarchy path and sidecar moves."""
    moves = _normalize_hierarchy_moves(entry)
    if not moves:
        return None
    planned = _plan_hierarchy_moves(ctx, entry, moves)
    _prepare_hierarchy_destinations(planned)
    for plan in planned:
        plan.source.replace(plan.temp)
    for plan in planned:
        plan.temp.replace(plan.destination)
    first = planned[0].move
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName(entry.action),
        target_asset_id=first.asset_id,
        from_path=first.from_path,
        to_path=first.to_path,
        temp_path=None,
        duration_ns=0,
    )


def _normalize_hierarchy_moves(entry: JournalEntry) -> list[_HierarchyMove]:
    moves = _normalize_hierarchy_move_list(entry.state_delta["path_moves"])
    moves.extend(_normalize_hierarchy_move_list(entry.state_delta["sidecar_moves"]))
    return moves


def _normalize_hierarchy_move_list(raw_moves: object) -> list[_HierarchyMove]:
    if not isinstance(raw_moves, list):
        raise TypeError("hierarchy move list must be a list")
    moves: list[_HierarchyMove] = []
    for raw_move in raw_moves:
        if not isinstance(raw_move, Mapping):
            raise TypeError("hierarchy move must be a mapping")
        move = cast("Mapping[str, object]", raw_move)
        moves.append(
            _HierarchyMove(
                asset_id=str(move["asset_id"]),
                from_path=str(move["from_path"]),
                to_path=str(move["to_path"]),
            )
        )
    return moves


def _plan_hierarchy_moves(
    ctx: FilesystemPhaseBContext,
    entry: JournalEntry,
    moves: list[_HierarchyMove],
) -> list[_PlannedHierarchyMove]:
    resolved_moves: list[tuple[_HierarchyMove, Path, Path]] = []
    source_paths: set[Path] = set()
    destination_paths: set[Path] = set()
    for move in moves:
        source = resolve_under_library(Path(move.from_path), ctx.library_root)
        destination = resolve_under_library(Path(move.to_path), ctx.library_root)
        if source in source_paths:
            raise ValueError(f"duplicate hierarchy source path: {move.from_path}")
        if destination in destination_paths:
            raise ValueError(f"duplicate hierarchy destination path: {move.to_path}")
        source_paths.add(source)
        destination_paths.add(destination)
        resolved_moves.append((move, source, destination))
    planned: list[_PlannedHierarchyMove] = []
    temp_paths: set[Path] = set()
    event_token = _hierarchy_temp_event_token(entry.event_id)
    for index, (move, source, destination) in enumerate(resolved_moves):
        reserved_paths = source_paths | destination_paths | temp_paths
        temp = _hierarchy_temp_path(source, event_token, index, reserved_paths)
        temp_paths.add(temp)
        planned.append(
            _PlannedHierarchyMove(
                move=move,
                source=source,
                destination=destination,
                temp=temp,
            )
        )
    for source in source_paths:
        if not source.exists():
            raise FileNotFoundError(source)
    for destination in destination_paths:
        if destination.exists() and destination not in source_paths:
            raise FileExistsError(destination)
    for plan in planned:
        if plan.temp.exists():
            raise FileExistsError(plan.temp)
    return planned


def _hierarchy_temp_event_token(event_id: str) -> str:
    token = _UNSAFE_HIERARCHY_TEMP_TOKEN_CHARS.sub("_", event_id)[
        :_HIERARCHY_TEMP_TOKEN_PREFIX_LENGTH
    ]
    if not token:
        token = "event"
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8]
    return f"{token}-{digest}"


def _hierarchy_temp_path(
    source: Path,
    event_token: str,
    index: int,
    reserved_paths: set[Path],
) -> Path:
    candidate = source.with_name(f".chaos-hierarchy-{event_token}-{index}.tmp")
    if not _path_conflicts_with_reserved(candidate, reserved_paths):
        return candidate
    for attempt in range(1, _HIERARCHY_TEMP_PATH_ATTEMPTS):
        candidate = source.with_name(f".chaos-hierarchy-{event_token}-{index}-{attempt}.tmp")
        if not _path_conflicts_with_reserved(candidate, reserved_paths):
            return candidate
    raise ValueError("could not allocate hierarchy temporary path")


def _path_conflicts_with_reserved(candidate: Path, reserved_paths: set[Path]) -> bool:
    for reserved_path in reserved_paths:
        if candidate == reserved_path:
            return True
        if candidate in reserved_path.parents:
            return True
        if reserved_path in candidate.parents:
            return True
    return False


def _prepare_hierarchy_destinations(planned: list[_PlannedHierarchyMove]) -> None:
    for plan in planned:
        plan.destination.parent.mkdir(parents=True, exist_ok=True)


def _slow_copy_start(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Stage a slow-copy at ``temp_path``; defer rename until commit."""
    asset_id = entry.target_ids[0]
    initial_path = str(entry.state_delta["initial_path_at_start"])
    temp_path = str(entry.state_delta["temp_path"])
    final_path = str(entry.state_delta["final_path"])
    src = ctx.library_root / initial_path
    dst = ctx.library_root / temp_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    ctx.pending_slow_copy[entry.event_id] = _PendingSlowCopy(
        asset_id=asset_id,
        initial_path=initial_path,
        temp_path=temp_path,
    )
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_START,
        target_asset_id=asset_id,
        from_path=initial_path,
        to_path=final_path,
        temp_path=temp_path,
        duration_ns=0,
    )


def _slow_copy_commit(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Promote a staged slow-copy to its final path.

    When ``initial_path`` differs from ``final_path``, the initial file
    is unlinked first so the ``replace`` lands on a free path even on
    filesystems that reject ``rename`` over an existing inode.
    """
    if not isinstance(entry, CommittedJournalEntry):
        raise ChaosLibrarianValueError(f"{entry.event_id} is not a committed slow_copy entry")
    pending = ctx.pending_slow_copy.pop(entry.related_event_id)
    final_path = str(entry.state_delta["final_path"])
    promote_slow_copy(
        library_root=ctx.library_root,
        initial_path=pending.initial_path,
        temp_path=pending.temp_path,
        final_path=final_path,
    )
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        target_asset_id=pending.asset_id,
        from_path=pending.temp_path,
        to_path=final_path,
        temp_path=None,
        duration_ns=0,
    )


def promote_slow_copy(
    *,
    library_root: Path,
    initial_path: str,
    temp_path: str,
    final_path: str,
) -> None:
    """Promote a staged slow-copy temp file to its final path."""
    if initial_path != final_path:
        (library_root / initial_path).unlink(missing_ok=True)
    dst = library_root / final_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    (library_root / temp_path).replace(dst)


_DISPATCH: Final[
    dict[
        TimelineActionName,
        Callable[[FilesystemPhaseBContext, JournalEntry], FilesystemAction | None],
    ]
] = {
    TimelineActionName.MOVE_ASSET: _move_asset,
    TimelineActionName.RENAME_FILE: _move_asset,
    TimelineActionName.DELETE_FILE: _delete_file,
    TimelineActionName.ADD_FILE: _add_file,
    TimelineActionName.REMOVE_SIDECAR: _remove_sidecar,
    TimelineActionName.TOUCH_MTIME: _touch_mtime,
    TimelineActionName.SLOW_COPY_START: _slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _move_asset,
    TimelineActionName.MOVE_BETWEEN_ROOTS: _move_asset,
    TimelineActionName.RENUMBER_EPISODE: _hierarchy_moves,
    TimelineActionName.MOVE_EPISODE_TO_SEASON: _hierarchy_moves,
    TimelineActionName.RENAME_SEASON: _hierarchy_moves,
    TimelineActionName.RENUMBER_DISC: _hierarchy_moves,
    TimelineActionName.MOVE_TRACK_TO_DISC: _hierarchy_moves,
    TimelineActionName.SWAP_EPISODE_NUMBERS: _hierarchy_moves,
    TimelineActionName.SWAP_DISC_NUMBERS: _hierarchy_moves,
    TimelineActionName.SWAP_TRACK_NUMBERS: _hierarchy_moves,
}

_HIERARCHY_ACTIONS: Final[frozenset[TimelineActionName]] = HIERARCHY_TIMELINE_ACTIONS
