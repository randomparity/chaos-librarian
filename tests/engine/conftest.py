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
    AddFileEvent,
    ArchiveFileEvent,
    AudioChannelLayout,
    CorruptContainerHeaderEvent,
    CorruptPacketRangeEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    MoveEpisodeToSeasonEvent,
    MoveTrackToDiscEvent,
    NetworkLagCommitEvent,
    NetworkLagEffect,
    NetworkLagStartEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    RenameFileEvent,
    RenameSeasonEvent,
    RenumberDiscEvent,
    RenumberEpisodeEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
    TouchMtimeEvent,
    TruncateFileEvent,
    UpdateSidecarEvent,
    WriteInvalidDurationMetadataEvent,
    WrongOracleHashEvent,
)
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState, build_initial_state

type _TerminalEvent = (
    MoveAssetEvent
    | RenameFileEvent
    | DeleteFileEvent
    | AddFileEvent
    | CreateSidecarEvent
    | SlowCopyStartEvent
    | SlowCopyCommitEvent
    | ArchiveFileEvent
    | MoveBetweenRootsEvent
    | RenumberEpisodeEvent
    | MoveEpisodeToSeasonEvent
    | RenameSeasonEvent
    | RenumberDiscEvent
    | MoveTrackToDiscEvent
    | ReencodeVideoEvent
    | ReencodeAudioEvent
    | RemuxContainerEvent
    | EditMetadataEvent
    | EmbedSubtitleEvent
    | ExtractSubtitleEvent
    | RemoveSidecarEvent
    | UpdateSidecarEvent
    | CorruptContainerHeaderEvent
    | TruncateFileEvent
    | CorruptPacketRangeEvent
    | WriteInvalidDurationMetadataEvent
    | TouchMtimeEvent
    | WrongOracleHashEvent
    | NetworkLagStartEvent
    | NetworkLagCommitEvent
)

# Shared id linking the pre-applied slow_copy_start event to the commit
# event the registry produces. Used by both `_prepare_pending_slow_copy`
# (as the start event's id) and the SLOW_COPY_COMMIT builder
# (as `for_=`); the engine resolves the commit by matching this string,
# so the two must stay in sync.
_PENDING_COPY_ID: Final = "start"
_PENDING_LAG_AFTER_ID: Final = "lag_after"
_PENDING_LAG_ID: Final = "lag_start"

# Shared path linking the pre-applied create_sidecar event to the
# embed/remove/update terminal events. The sidecar handlers look the
# sidecar up by (target, path), so the prereq and terminal must agree.
_PENDING_SIDECAR_PATH: Final = "library/movies-hd/asset_hd_main.eng.srt"
_TEST_RUN_ID: Final = uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01")


def _engine_event_context(
    scenario_id: str = "sc_test",
    *,
    run_id: uuid.UUID = _TEST_RUN_ID,
    resolved_seed: int = 42,
) -> EngineEventContext:
    return EngineEventContext(
        run_id=run_id,
        scenario_id=scenario_id,
        resolved_seed=resolved_seed,
    )


def _build_minimal_scenario(
    *,
    roots: list[tuple[str, str]],
    movies: list[tuple[str, str, str]],
    archive_root: str | None = None,
    with_media_tracks: bool = False,
    with_declared_subtitle: bool = False,
) -> Scenario:
    """Build a minimal Scenario for engine-level tests.

    Each ``movies`` entry is ``(movie_id, asset_id, container)``; the helper
    synthesizes one variant and one bundle per movie, each holding the
    single declared asset. ``roots`` entries are ``(root_id, root_path)``;
    the first root is the primary one ``build_initial_state`` uses to
    synthesize initial location paths.

    The returned Scenario carries an empty timeline — these tests probe
    initial state only.

    Args:
        roots: declared library roots, in scenario order.
        movies: one tuple per asset, each producing its own movie / variant
            / bundle wrapper.
        archive_root: optional ``library.archive_root`` value. ``None``
            leaves the field at its default; the literal string
            ``"archive"`` is the sentinel meaning "default subdir of the
            primary root".
        with_media_tracks: if True, every synthesized asset gets a
            ``video`` track (color_bars / h264 / hd) and one ``audio``
            track (aac / stereo / eng). Sprint 7 handlers that probe
            asset internals (re-encode, remux, edit_metadata, extract)
            require these fields.
        with_declared_subtitle: if True, every synthesized asset also
            gets one declared subtitle track (srt / eng / sidecar).
            extract_subtitle requires a declared subtitle track on the
            asset.

    Returns:
        A fully-validated Scenario at ``schema_version=22``.
    """
    library: dict[str, object] = {
        "roots": [{"id": root_id, "path": path} for root_id, path in roots],
    }
    if archive_root is not None:
        library["archive_root"] = archive_root

    def _asset(asset_id: str, container: str) -> dict[str, object]:
        asset: dict[str, object] = {
            "id": asset_id,
            "role": "primary_video",
            "container": container,
            "duration_seconds": 1,
        }
        if with_media_tracks:
            asset["video"] = {
                "source": "color_bars",
                "codec": "h264",
                "resolution": "hd",
            }
            asset["audio"] = [
                {"codec": "aac", "channels": "stereo", "language": "eng"},
            ]
        if with_declared_subtitle:
            asset["subtitles"] = [
                {"codec": "srt", "language": "eng", "mode": "sidecar"},
            ]
        return asset

    scenario_movies = [
        {
            "id": movie_id,
            "title": movie_id,
            "layout": "movie_flat",
            "variants": [
                {
                    "id": f"variant_{movie_id}",
                    "label": "default",
                    "bundle": {
                        "id": f"bundle_{movie_id}",
                        "assets": [_asset(asset_id, container)],
                    },
                }
            ],
        }
        for movie_id, asset_id, container in movies
    ]

    return Scenario.model_validate(
        {
            "schema_version": 22,
            "scenario_id": "engine-test",
            "seed": 1,
            "duration_scale": "short",
            "library": library,
            "movies": scenario_movies,
            "series": [],
            "artists": [],
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
    TimelineActionName.ADD_FILE: lambda: AddFileEvent(
        id="ev", at="1ns", target="asset_hd_main", to="movies-hd/restored.mkv"
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
    TimelineActionName.RENUMBER_EPISODE: lambda: RenumberEpisodeEvent(
        id="ev", at="0ns", target="episode_001", episode_number=2
    ),
    TimelineActionName.MOVE_EPISODE_TO_SEASON: lambda: MoveEpisodeToSeasonEvent(
        id="ev",
        at="0ns",
        target="episode_001",
        to_season="season_002",
        episode_number=1,
    ),
    TimelineActionName.RENAME_SEASON: lambda: RenameSeasonEvent(
        id="ev", at="0ns", target="season_001", title="Renamed"
    ),
    TimelineActionName.RENUMBER_DISC: lambda: RenumberDiscEvent(
        id="ev", at="0ns", target="disc_001", disc_number=2
    ),
    TimelineActionName.MOVE_TRACK_TO_DISC: lambda: MoveTrackToDiscEvent(
        id="ev", at="0ns", target="track_001", to_disc="disc_002", track_number=2
    ),
    TimelineActionName.REENCODE_VIDEO: lambda: ReencodeVideoEvent(
        id="ev", at="0ns", target="asset_hd_main", resolution="sd", codec="h264"
    ),
    TimelineActionName.REENCODE_AUDIO: lambda: ReencodeAudioEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        from_channels=AudioChannelLayout.STEREO,
        to_channels=AudioChannelLayout.MONO,
    ),
    TimelineActionName.REMUX_CONTAINER: lambda: RemuxContainerEvent(
        id="ev", at="0ns", target="asset_hd_main", to_container="mp4"
    ),
    TimelineActionName.EDIT_METADATA: lambda: EditMetadataEvent(
        id="ev", at="0ns", target="asset_hd_main", fields={"title": "X"}
    ),
    TimelineActionName.EMBED_SUBTITLE: lambda: EmbedSubtitleEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        sidecar_path=_PENDING_SIDECAR_PATH,
    ),
    TimelineActionName.EXTRACT_SUBTITLE: lambda: ExtractSubtitleEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        to="library/movies-hd/asset_hd_main.fra.srt",
        language="fra",
    ),
    TimelineActionName.REMOVE_SIDECAR: lambda: RemoveSidecarEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        sidecar_path=_PENDING_SIDECAR_PATH,
    ),
    TimelineActionName.UPDATE_SIDECAR: lambda: UpdateSidecarEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        sidecar_path=_PENDING_SIDECAR_PATH,
    ),
    TimelineActionName.CORRUPT_CONTAINER_HEADER: lambda: CorruptContainerHeaderEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        bytes=64,
    ),
    TimelineActionName.TRUNCATE_FILE: lambda: TruncateFileEvent(
        id="ev", at="0ns", target="asset_hd_main", keep_bytes=64
    ),
    TimelineActionName.CORRUPT_PACKET_RANGE: lambda: CorruptPacketRangeEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        packet_start=0,
        packet_count=2,
    ),
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: lambda: WriteInvalidDurationMetadataEvent(
        id="ev", at="0ns", target="asset_hd_main", value="not-a-duration"
    ),
    TimelineActionName.TOUCH_MTIME: lambda: TouchMtimeEvent(
        id="ev", at="0ns", target="asset_hd_main", offset="2s"
    ),
    TimelineActionName.WRONG_ORACLE_HASH: lambda: WrongOracleHashEvent(
        id="ev", at="0ns", target="asset_hd_main"
    ),
    TimelineActionName.NETWORK_LAG_START: lambda: NetworkLagStartEvent(
        id="ev",
        at="0ns",
        effect=NetworkLagEffect.DELAYED_RENAME,
        target="asset_hd_main",
        after=_PENDING_LAG_AFTER_ID,
        duration="1ns",
    ),
    TimelineActionName.NETWORK_LAG_COMMIT: lambda: NetworkLagCommitEvent(
        id="ev",
        at="1ns",
        for_=_PENDING_LAG_ID,
    ),
}

# Sprint 7 actions whose handlers probe asset video/audio fields; the
# scenario must declare matching tracks or the handler / preflight will
# crash on the missing data.
_NEEDS_MEDIA_TRACKS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
    }
)

# Sprint 7 actions whose minimal scenario requires a declared subtitle
# track on the asset (extract_subtitle picks a track; embed/remove/update
# operate on a sidecar that was created by the prereq below — they don't
# strictly need a declared subtitle, but adding one keeps the corpus
# consistent and matches the test_events_sidecar fixture).
_NEEDS_DECLARED_SUBTITLE: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
    }
)

# Sprint 7 actions whose terminal event references a sidecar that the
# minimal scenario must allocate first via a pre-applied create_sidecar.
_NEEDS_PENDING_SIDECAR: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
    }
)


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
        ctx=_engine_event_context(),
    )


def _prepare_deleted_asset(state: WorldState) -> None:
    """Pre-apply delete_file so ``add_file`` can restore a missing asset."""
    delete_event = DeleteFileEvent(id="prep_delete", at="0ns", target="asset_hd_main")
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=0, declared_index=0, event=delete_event),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )


def _prepare_pending_sidecar(state: WorldState) -> None:
    """Pre-apply create_sidecar so the embed/remove/update terminal can resolve it.

    The matching builders in ``_TERMINAL_EVENT_BUILDERS`` reference
    ``_PENDING_SIDECAR_PATH``; without this prerequisite
    ``state.sidecar_id_for_path`` would KeyError.
    """
    create_event = CreateSidecarEvent(
        id="prep_cs",
        at="0ns",
        target="asset_hd_main",
        to=_PENDING_SIDECAR_PATH,
        language="eng",
    )
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=0, declared_index=0, event=create_event),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )


def _prepare_network_lag_source(state: WorldState) -> None:
    """Pre-apply a rename whose delta a network_lag_start can reference."""
    rename_event = RenameFileEvent(
        id=_PENDING_LAG_AFTER_ID,
        at="0ns",
        target="asset_hd_main",
        to="movies-hd/lagged.mkv",
    )
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=0, declared_index=0, event=rename_event),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )


def _prepare_pending_network_lag(state: WorldState) -> None:
    """Pre-apply network_lag_start so commit can drain the pending lag."""
    _prepare_network_lag_source(state)
    start_event = NetworkLagStartEvent(
        id=_PENDING_LAG_ID,
        at="0ns",
        effect=NetworkLagEffect.DELAYED_RENAME,
        target="asset_hd_main",
        after=_PENDING_LAG_AFTER_ID,
        duration="1ns",
    )
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=0, declared_index=1, event=start_event),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )


def _minimal_scenario_for_action(
    action: TimelineActionName,
) -> tuple[Scenario, WorldState, ResolvedEvent]:
    """Build the smallest scenario whose terminal event is ``action``.

    Returns (scenario, prepared_world_state, resolved_event). The state is
    pre-advanced through any prerequisite events (e.g. ``slow_copy_commit``
    needs its matching ``slow_copy_start`` applied first so
    ``state.pending_slow_copies`` is populated; the four sidecar-touching
    Sprint 7 actions need a ``create_sidecar`` pre-applied so
    ``sidecar_id_for_path`` can resolve their target).
    """
    if action in {
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
    }:
        scenario = _build_minimal_series_scenario()
        state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
        builder = _TERMINAL_EVENT_BUILDERS[action]
        return scenario, state, ResolvedEvent(at_ns=1, declared_index=0, event=builder())

    if action in {TimelineActionName.RENUMBER_DISC, TimelineActionName.MOVE_TRACK_TO_DISC}:
        scenario = _build_minimal_music_scenario()
        state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
        builder = _TERMINAL_EVENT_BUILDERS[action]
        return scenario, state, ResolvedEvent(at_ns=1, declared_index=0, event=builder())

    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        movies=[("movie_001", "asset_hd_main", "mkv")],
        archive_root=None,
        with_media_tracks=action in _NEEDS_MEDIA_TRACKS,
        with_declared_subtitle=action in _NEEDS_DECLARED_SUBTITLE,
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
    if action is TimelineActionName.SLOW_COPY_COMMIT:
        _prepare_pending_slow_copy(state)
    if action is TimelineActionName.ADD_FILE:
        _prepare_deleted_asset(state)
    if action in _NEEDS_PENDING_SIDECAR:
        _prepare_pending_sidecar(state)
    if action is TimelineActionName.NETWORK_LAG_START:
        _prepare_network_lag_source(state)
    if action is TimelineActionName.NETWORK_LAG_COMMIT:
        _prepare_pending_network_lag(state)

    builder = _TERMINAL_EVENT_BUILDERS.get(action)
    if builder is None:
        raise AssertionError(f"unhandled action: {action!r}")
    event = builder()
    return scenario, state, ResolvedEvent(at_ns=1, declared_index=0, event=event)


def _build_minimal_series_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 22,
            "scenario_id": "engine-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "tv", "path": "library/tv"}]},
            "movies": [],
            "series": [
                {
                    "id": "series_001",
                    "title": "Series",
                    "layout": "season_folders",
                    "episode_naming": "sxxexx_title",
                    "seasons": [
                        {
                            "id": "season_001",
                            "season_number": 1,
                            "title": "One",
                            "episodes": [
                                {
                                    "id": "episode_001",
                                    "episode_number": 1,
                                    "title": "Pilot",
                                    "variants": [
                                        {
                                            "id": "variant_episode_001",
                                            "label": "default",
                                            "bundle": {
                                                "id": "bundle_episode_001",
                                                "assets": [
                                                    {
                                                        "id": "asset_hd_main",
                                                        "role": "primary_video",
                                                        "container": "mkv",
                                                        "duration_seconds": 1,
                                                    }
                                                ],
                                            },
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "season_002",
                            "season_number": 2,
                            "title": "Two",
                            "episodes": [],
                        },
                    ],
                }
            ],
            "artists": [],
            "timeline": [],
        }
    )


def _build_minimal_music_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 22,
            "scenario_id": "engine-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "music", "path": "library/music"}]},
            "movies": [],
            "series": [],
            "artists": [
                {
                    "id": "artist_001",
                    "name": "Artist",
                    "layout": "artist_album_disc",
                    "track_naming": "disc_track_number_title",
                    "albums": [
                        {
                            "id": "album_001",
                            "title": "Album",
                            "discs": [
                                {
                                    "id": "disc_001",
                                    "disc_number": 1,
                                    "tracks": [
                                        {
                                            "id": "track_001",
                                            "track_number": 1,
                                            "title": "Song",
                                            "variants": [
                                                {
                                                    "id": "variant_track_001",
                                                    "label": "default",
                                                    "bundle": {
                                                        "id": "bundle_track_001",
                                                        "assets": [
                                                            {
                                                                "id": "asset_hd_main",
                                                                "role": "audio",
                                                                "container": "flac",
                                                                "duration_seconds": 1,
                                                            }
                                                        ],
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                },
                                {"id": "disc_002", "disc_number": 2, "tracks": []},
                            ],
                        }
                    ],
                }
            ],
            "timeline": [],
        }
    )
