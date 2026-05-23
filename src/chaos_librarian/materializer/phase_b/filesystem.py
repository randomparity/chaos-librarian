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

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.contract.scenario import Asset, TimelineActionName
from chaos_librarian.materializer.errors import FilesystemActionError

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
        # ``assert isinstance``) still route through cleanup + exit 5
        # instead of escaping the dispatcher unwrapped.
        target_asset = entry.target_ids[0] if entry.target_ids else None
        raise FilesystemActionError(
            f"{entry.action} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id,
            cause=exc,
            action=action,
            asset_id=target_asset,
        ) from exc
    return result.model_copy(update={"duration_ns": time.monotonic_ns() - started})


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


def _slow_copy_start(ctx: FilesystemPhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Stage a slow-copy at ``temp_path``; defer rename until commit."""
    asset_id = entry.target_ids[0]
    initial_path = str(entry.state_delta["initial_path_at_start"])
    temp_path = str(entry.state_delta["temp_path"])
    final_path = str(entry.state_delta["final_path"])
    src = ctx.library_root / initial_path
    dst = ctx.library_root / temp_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
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
    assert isinstance(entry, CommittedJournalEntry)
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
    dict[TimelineActionName, Callable[[FilesystemPhaseBContext, JournalEntry], FilesystemAction]]
] = {
    TimelineActionName.MOVE_ASSET: _move_asset,
    TimelineActionName.RENAME_FILE: _move_asset,
    TimelineActionName.DELETE_FILE: _delete_file,
    TimelineActionName.ADD_FILE: _add_file,
    TimelineActionName.REMOVE_SIDECAR: _remove_sidecar,
    TimelineActionName.SLOW_COPY_START: _slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _move_asset,
    TimelineActionName.MOVE_BETWEEN_ROOTS: _move_asset,
}
