"""Bounded deterministic filesystem activity on an existing imported topology."""

from pathlib import PurePosixPath
from typing import Final

from chaos_librarian.contract.scenario import MoveAssetEvent, RenameFileEvent, TouchMtimeEvent
from chaos_librarian.determinism.rng import RngStreams
from chaos_librarian.determinism.trace import TraceRecorder

MAX_IMPORT_CHAOS_EVENTS: Final = 1000


def plan_import_timeline(
    *,
    assets: list[tuple[str, str]],
    root_path: str,
    reserved_ids: set[str],
    reserved_paths: set[str],
    seed: int,
    event_count: int,
) -> list[dict[str, object]]:
    """Return imported-safe events without changing the supplied reservations."""
    if seed < 0 or not 1 <= event_count <= MAX_IMPORT_CHAOS_EVENTS:
        raise ValueError("import chaos requires seed >= 0 and event_count in 1..1000")
    if not assets:
        raise ValueError("import chaos requires at least one surviving asset")
    rng = RngStreams(seed, TraceRecorder()).stream("import-chaos")
    assets = sorted(assets)
    ids = set(reserved_ids)
    occupied = {PurePosixPath(path) for path in reserved_paths}
    directory = PurePosixPath(root_path) / "import-chaos"
    suffix = 0
    while any(path == directory or directory in path.parents for path in occupied):
        suffix += 1
        directory = PurePosixPath(root_path) / f"import-chaos-{suffix}"
    events: list[dict[str, object]] = []
    for index in range(1, event_count + 1):
        candidate = f"import-chaos-{index:04d}"
        event_id = candidate
        suffix = 0
        while event_id in ids:
            suffix += 1
            event_id = f"{candidate}-{suffix}"
        ids.add(event_id)
        asset_id, container = rng.choice(assets)
        action = (
            "rename_file"
            if index == 1
            else rng.choice(("rename_file", "move_asset", "touch_mtime"))
        )
        at = f"{index}ns"
        if action == "touch_mtime":
            event = TouchMtimeEvent(id=event_id, at=at, target=asset_id, offset="1s")
        else:
            event_type = RenameFileEvent if action == "rename_file" else MoveAssetEvent
            event = event_type(
                id=event_id,
                at=at,
                target=asset_id,
                to=(directory / f"{event_id}.{container}").as_posix(),
            )
        events.append(event.model_dump(mode="json", exclude_none=True))
    return events
