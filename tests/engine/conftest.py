"""Shared helpers for engine-level tests.

The ``_build_minimal_scenario`` factory below is used by multiple Sprint 6
test modules (``test_state.py`` for root/archive lookups, plus the
filesystem-event handler tests landing in later tasks) to spin up a
contract-valid ``Scenario`` without restating the full nested literal at
every call site.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Final

from chaos_librarian.contract.scenario import (
    ArchiveFileEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    RenameFileEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState, build_initial_state

type _TerminalEvent = (
    MoveAssetEvent
    | RenameFileEvent
    | DeleteFileEvent
    | CreateSidecarEvent
    | SlowCopyStartEvent
    | SlowCopyCommitEvent
    | ArchiveFileEvent
    | MoveBetweenRootsEvent
)

# Shared id linking the pre-applied slow_copy_start event to the commit
# event the registry produces. Used by both `_prepare_pending_slow_copy`
# (as the start event's id) and the SLOW_COPY_COMMIT builder
# (as `for_=`); the engine resolves the commit by matching this string,
# so the two must stay in sync.
_PENDING_COPY_ID: Final = "start"


def _build_minimal_scenario(
    *,
    roots: list[tuple[str, str]],
    works: list[tuple[str, str, str]],
    archive_root: str | None = None,
) -> Scenario:
    """Build a minimal Scenario for engine-level tests.

    Each ``works`` entry is ``(work_id, asset_id, container)``; the helper
    synthesizes one variant and one bundle per work, each holding the
    single declared asset. ``roots`` entries are ``(root_id, root_path)``;
    the first root is the primary one ``build_initial_state`` uses to
    synthesize initial location paths.

    The returned Scenario carries an empty timeline — these tests probe
    initial state only.

    Args:
        roots: declared library roots, in scenario order.
        works: one tuple per asset, each producing its own work / variant
            / bundle wrapper.
        archive_root: optional ``library.archive_root`` value. ``None``
            leaves the field at its default; the literal string
            ``"archive"`` is the sentinel meaning "default subdir of the
            primary root".

    Returns:
        A fully-validated Scenario at ``schema_version=5``.
    """
    library: dict[str, object] = {
        "roots": [{"id": root_id, "path": path} for root_id, path in roots],
    }
    if archive_root is not None:
        library["archive_root"] = archive_root

    scenario_works = [
        {
            "id": work_id,
            "title": work_id,
            "variants": [
                {
                    "id": f"variant_{work_id}",
                    "label": "default",
                    "bundle": {
                        "id": f"bundle_{work_id}",
                        "assets": [
                            {
                                "id": asset_id,
                                "role": "primary_video",
                                "container": container,
                                "duration_seconds": 1,
                            }
                        ],
                    },
                }
            ],
        }
        for work_id, asset_id, container in works
    ]

    return Scenario.model_validate(
        {
            "schema_version": 5,
            "scenario_id": "engine-test",
            "seed": 1,
            "duration_scale": "short",
            "library": library,
            "works": scenario_works,
            "timeline": [],
        }
    )


def _resolve_archive_file(
    scenario: Scenario,
    *,
    event_id: str,
    target: str,
) -> ResolvedEvent:
    """Build a ResolvedEvent wrapping an ``ArchiveFileEvent`` for tests.

    Mirrors the shape that ``resolve_timeline`` would produce, without
    requiring the event to live on the scenario's timeline. Sprint 6 task 17
    reuses this helper for materializer dispatcher tests.
    """
    del scenario  # only present to mirror the engine resolver's call signature
    event = ArchiveFileEvent(id=event_id, at="0ns", target=target)
    return ResolvedEvent(at_ns=1, declared_index=0, event=event)


def _resolve_move_between_roots(
    scenario: Scenario,
    *,
    event_id: str,
    target: str,
    from_root_id: str,
    to_root_id: str,
) -> ResolvedEvent:
    """Build a ResolvedEvent wrapping a ``MoveBetweenRootsEvent`` for tests.

    Mirrors the shape that ``resolve_timeline`` would produce, without
    requiring the event to live on the scenario's timeline. Sprint 6 task 17
    reuses this helper for materializer dispatcher tests.
    """
    del scenario  # only present to mirror the engine resolver's call signature
    event = MoveBetweenRootsEvent(
        id=event_id,
        at="0ns",
        target=target,
        from_root_id=from_root_id,
        to_root_id=to_root_id,
    )
    return ResolvedEvent(at_ns=1, declared_index=0, event=event)


_TERMINAL_EVENT_BUILDERS: Final[dict[TimelineActionName, Callable[[], _TerminalEvent]]] = {
    TimelineActionName.MOVE_ASSET: lambda: MoveAssetEvent(
        id="ev", at="0ns", target="asset_hd_main", to="movies-hd/new.mkv"
    ),
    TimelineActionName.RENAME_FILE: lambda: RenameFileEvent(
        id="ev", at="0ns", target="asset_hd_main", to="movies-hd/renamed.mkv"
    ),
    TimelineActionName.DELETE_FILE: lambda: DeleteFileEvent(
        id="ev", at="0ns", target="asset_hd_main"
    ),
    TimelineActionName.CREATE_SIDECAR: lambda: CreateSidecarEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        to="movies-hd/asset_hd_main.en.srt",
        language="en",
    ),
    TimelineActionName.SLOW_COPY_START: lambda: SlowCopyStartEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        to="movies-hd/final.mkv",
        temp_path="movies-hd/temp.mkv",
        duration="1ns",
    ),
    TimelineActionName.SLOW_COPY_COMMIT: lambda: SlowCopyCommitEvent(
        id="ev", at="1ns", for_=_PENDING_COPY_ID
    ),
    TimelineActionName.ARCHIVE_FILE: lambda: ArchiveFileEvent(
        id="ev", at="0ns", target="asset_hd_main"
    ),
    TimelineActionName.MOVE_BETWEEN_ROOTS: lambda: MoveBetweenRootsEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        from_root_id="movies-hd",
        to_root_id="cold-storage",
    ),
}


def _prepare_pending_slow_copy(state: WorldState) -> None:
    """Pre-apply slow_copy_start so ``state.pending_slow_copies`` carries the id.

    The matching builder in ``_TERMINAL_EVENT_BUILDERS`` returns a
    ``SlowCopyCommitEvent`` referencing ``_PENDING_COPY_ID``; without this
    prerequisite the handler's lookup would KeyError.
    """
    start_event = SlowCopyStartEvent(
        id=_PENDING_COPY_ID,
        at="0ns",
        target="asset_hd_main",
        to="movies-hd/final.mkv",
        temp_path="movies-hd/temp.mkv",
        duration="1ns",
    )
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=0, declared_index=0, event=start_event),
        ids=IdAllocator(TraceRecorder()),
        run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
        scenario_id="sc_test",
    )


def _minimal_scenario_for_action(
    action: TimelineActionName,
) -> tuple[Scenario, WorldState, ResolvedEvent]:
    """Build the smallest scenario whose terminal event is ``action``.

    Returns (scenario, prepared_world_state, resolved_event). The state is
    pre-advanced through any prerequisite events (e.g. ``slow_copy_commit``
    needs its matching ``slow_copy_start`` applied first so
    ``state.pending_slow_copies`` is populated).
    """
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root=None,
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
    if action is TimelineActionName.SLOW_COPY_COMMIT:
        _prepare_pending_slow_copy(state)

    builder = _TERMINAL_EVENT_BUILDERS.get(action)
    if builder is None:
        raise AssertionError(f"unhandled action: {action!r}")
    event = builder()
    return scenario, state, ResolvedEvent(at_ns=1, declared_index=0, event=event)
