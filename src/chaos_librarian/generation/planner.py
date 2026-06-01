"""Content and timeline planning for deterministic fuzz generation.

This module owns the canonical fuzz lane configuration (``LANE_CONFIGS``). Each
:class:`~chaos_librarian.generation.lanes.LaneConfig` pairs a lane's required
coverage cells with the ``required_events`` builder that satisfies them, so the
two cannot drift apart when a lane is added or changed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, cast

from pydantic import BaseModel

from chaos_librarian.contract import scenario as scenario_contract
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import (
    NetworkLagEffect,
    SidecarKind,
    TimelineActionName,
    TimelineEvent,
)
from chaos_librarian.determinism.rng import RngStream
from chaos_librarian.generation.lanes import (
    CELL_LAG_EFFECT_PREFIX,
    CELL_SIDE_NFO_OR_POSTER,
    CELL_SIDE_SUBTITLE,
    LaneConfig,
    action_cell,
    derive_required_profiles,
)

# Header bytes to overwrite for a corrupt-container-header event; within
# CorruptContainerHeaderEvent's 1..4096 range.
CORRUPT_HEADER_BYTES: Final = 64
# Bytes retained when truncating a file for a truncate-file event.
TRUNCATE_KEEP_BYTES: Final = 4096


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    asset_id: str
    container: str
    audio_codec: str
    audio_channels: str
    video_codec: str | None = None
    resolution: str | None = None
    role: str = "primary_video"
    duration_seconds: int | None = None
    has_declared_subtitle: bool = False


@dataclass(frozen=True, slots=True)
class EventReference:
    event_id: str
    at: str


@dataclass(slots=True)
class TimelinePlanner:
    root_id: str
    root_path: str
    secondary_root_id: str
    assets: list[PlannedAsset]
    events: list[TimelineEvent] = field(default_factory=list)
    sidecars_by_asset: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    media_unstable_assets: set[str] = field(default_factory=set)

    def next_index(self) -> int:
        return len(self.events) + 1

    def event_id(self, prefix: str) -> str:
        return f"fuzz_{self.next_index():04d}_{prefix}"

    def at(self) -> str:
        return f"{self.next_index()}ns"

    def append_event(self, event: TimelineEvent) -> None:
        """Append one concrete TimelineEvent model."""
        self.events.append(event)


def plan_payload_parts(
    *,
    seed: int,
    config: LaneConfig,
    rng: RngStream,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    assets = _planned_assets(config=config)
    library = _library_for_lane(config.lane)
    root_id, root_path = _event_root_for_lane(config.lane)
    planner = TimelinePlanner(
        root_id=root_id,
        root_path=root_path,
        secondary_root_id="cold-storage",
        assets=assets,
    )
    config.required_events(planner)
    _fill_remaining_events(planner=planner, config=config, rng=rng)
    return (
        library,
        _movies_payload(
            profile=config.profile,
            lane=config.lane,
            seed=seed,
            assets=assets,
            rng=rng,
        ),
        _series_payload(
            profile=config.profile,
            lane=config.lane,
            seed=seed,
            assets=assets,
            rng=rng,
        ),
        _artists_payload(
            profile=config.profile,
            lane=config.lane,
            seed=seed,
            assets=assets,
            rng=rng,
        ),
        _timeline_payload(planner.events),
    )


def _timeline_payload(events: list[TimelineEvent]) -> list[dict[str, object]]:
    return [_timeline_event_payload(event) for event in events]


def _timeline_event_payload(event: TimelineEvent) -> dict[str, object]:
    model = cast(BaseModel, event)
    return cast(
        "dict[str, object]",
        model.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def _library_for_lane(lane: FuzzLaneName) -> dict[str, object]:
    root_id, root_path = _event_root_for_lane(lane)
    roots: list[dict[str, str]] = [{"id": root_id, "path": root_path}]
    library: dict[str, object] = {"roots": roots}
    if lane is FuzzLaneName.CORE_FS:
        roots.append({"id": "cold-storage", "path": "cold-storage"})
        library["archive_root"] = "cold-storage"
    return library


def _event_root_for_lane(lane: FuzzLaneName) -> tuple[str, str]:
    if lane is FuzzLaneName.TV_TOPOLOGY:
        return ("tv", "tv")
    if lane is FuzzLaneName.MUSIC_TOPOLOGY:
        return ("music", "music")
    return ("movies-hd", "movies-hd")


def _planned_assets(*, config: LaneConfig) -> list[PlannedAsset]:
    if config.series:
        return _planned_series_assets()
    if config.artists:
        return _planned_track_assets()

    containers = ("mkv", "mp4")
    resolutions = ("sd", "hd", "1080p")
    channels = ("mono", "stereo", "5.1")
    assets: list[PlannedAsset] = []
    for index in range(1, config.movies + 1):
        assets.append(
            PlannedAsset(
                asset_id=f"asset_{index:03d}",
                container=containers[(index - 1) % len(containers)],
                audio_codec="aac",
                audio_channels=channels[(index - 1) % len(channels)],
                video_codec="hevc" if index % 5 == 0 else "h264",
                resolution=resolutions[(index - 1) % len(resolutions)],
                has_declared_subtitle=(
                    index % 3 == 0 or (config.lane is FuzzLaneName.SIDECAR_SUBTITLE and index == 1)
                ),
            )
        )
    return assets


def _planned_series_assets() -> list[PlannedAsset]:
    return [
        PlannedAsset(
            asset_id="asset_001",
            container="mkv",
            audio_codec="aac",
            audio_channels="stereo",
            video_codec="h264",
            resolution="hd",
            duration_seconds=5,
        ),
        PlannedAsset(
            asset_id="asset_002",
            container="mp4",
            audio_codec="aac",
            audio_channels="stereo",
            video_codec="h264",
            resolution="1080p",
            duration_seconds=5,
        ),
    ]


def _planned_track_assets() -> list[PlannedAsset]:
    return [
        PlannedAsset(
            asset_id="track_asset_001",
            container="flac",
            audio_codec="flac",
            audio_channels="stereo",
            role="primary_audio",
            duration_seconds=5,
        ),
        PlannedAsset(
            asset_id="track_asset_002",
            container="m4a",
            audio_codec="aac",
            audio_channels="stereo",
            role="primary_audio",
            duration_seconds=5,
        ),
    ]


def _movies_payload(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
    assets: list[PlannedAsset],
    rng: RngStream,
) -> list[dict[str, object]]:
    if lane in {FuzzLaneName.TV_TOPOLOGY, FuzzLaneName.MUSIC_TOPOLOGY}:
        return []

    movies: list[dict[str, object]] = []
    for index, asset in enumerate(assets, start=1):
        movies.append(
            {
                "id": f"movie_{index:03d}",
                "title": f"{profile.value} {lane.value} Movie {seed}-{index:03d}",
                "layout": "movie_flat",
                "variants": [
                    {
                        "id": f"variant_{index:03d}",
                        "label": lane.value,
                        "bundle": {
                            "id": f"bundle_{index:03d}",
                            "assets": [_asset_payload(asset=asset, rng=rng)],
                        },
                    }
                ],
            }
        )
    return movies


def _series_payload(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
    assets: list[PlannedAsset],
    rng: RngStream,
) -> list[dict[str, object]]:
    if lane is not FuzzLaneName.TV_TOPOLOGY:
        return []
    first, second = assets
    return [
        {
            "id": "series_001",
            "title": f"{profile.value} {lane.value} Series {seed}",
            "layout": "season_folders",
            "episode_naming": "sxxexx_title",
            "seasons": [
                {
                    "id": "season_001",
                    "season_number": 1,
                    "title": "Season 1",
                    "episodes": [
                        {
                            "id": "episode_001",
                            "episode_number": 1,
                            "title": "Pilot",
                            "variants": [
                                {
                                    "id": "variant_series_001",
                                    "label": lane.value,
                                    "bundle": {
                                        "id": "bundle_series_001",
                                        "assets": [_asset_payload(asset=first, rng=rng)],
                                    },
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "season_002",
                    "season_number": 2,
                    "title": "Season 2",
                    "episodes": [
                        {
                            "id": "episode_002",
                            "episode_number": 1,
                            "title": "Return",
                            "variants": [
                                {
                                    "id": "variant_series_002",
                                    "label": lane.value,
                                    "bundle": {
                                        "id": "bundle_series_002",
                                        "assets": [_asset_payload(asset=second, rng=rng)],
                                    },
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    ]


def _artists_payload(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
    assets: list[PlannedAsset],
    rng: RngStream,
) -> list[dict[str, object]]:
    if lane is not FuzzLaneName.MUSIC_TOPOLOGY:
        return []
    first, second = assets
    return [
        {
            "id": "artist_001",
            "name": f"{profile.value} {lane.value} Artist {seed}",
            "layout": "artist_album_disc",
            "track_naming": "disc_track_number_title",
            "albums": [
                {
                    "id": "album_001",
                    "title": f"{lane.value} Album {seed}",
                    "discs": [
                        {
                            "id": "disc_001",
                            "disc_number": 1,
                            "tracks": [
                                {
                                    "id": "track_001",
                                    "track_number": 1,
                                    "title": "Opening",
                                    "variants": [
                                        {
                                            "id": "variant_track_001",
                                            "label": "flac",
                                            "bundle": {
                                                "id": "bundle_track_001",
                                                "assets": [_asset_payload(asset=first, rng=rng)],
                                            },
                                        }
                                    ],
                                },
                                {
                                    "id": "track_002",
                                    "track_number": 2,
                                    "title": "Return",
                                    "variants": [
                                        {
                                            "id": "variant_track_002",
                                            "label": "m4a",
                                            "bundle": {
                                                "id": "bundle_track_002",
                                                "assets": [_asset_payload(asset=second, rng=rng)],
                                            },
                                        }
                                    ],
                                },
                            ],
                        },
                        {
                            # Intentionally non-sequential (gap after disc_001=1):
                            # the timeline renumbers disc_001 to 2, so disc_002
                            # must stay at 3 to avoid a disc_number collision.
                            "id": "disc_002",
                            "disc_number": 3,
                            "tracks": [],
                        },
                    ],
                }
            ],
        }
    ]


def _asset_payload(asset: PlannedAsset, rng: RngStream) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": asset.asset_id,
        "role": asset.role,
        "container": asset.container,
        # Fallback duration (seconds) when the asset declares none; short to
        # keep generated fixtures cheap to materialize.
        "duration_seconds": asset.duration_seconds or rng.randint(2, 8),
    }
    if asset.video_codec is not None and asset.resolution is not None:
        payload["video"] = {
            "source": "color_bars",
            "codec": asset.video_codec,
            "resolution": asset.resolution,
        }
    payload["audio"] = [
        {
            "source": "sine",
            "codec": asset.audio_codec,
            "channels": asset.audio_channels,
            "language": "eng",
        }
    ]
    if asset.has_declared_subtitle:
        payload["subtitles"] = [
            {
                "source": "generated_srt",
                "codec": "srt",
                "language": "eng",
                "mode": "sidecar",
            }
        ]
    return payload


def _emit_smoke_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _move_asset(planner, assets[0])
    _rename_file(planner, assets[1])
    _edit_metadata(planner, assets[0])
    _create_nfo_sidecar(planner, assets[0])
    _update_first_sidecar(planner)


def _emit_core_fs_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _move_asset(planner, assets[0])
    _rename_file(planner, assets[1])
    _delete_file(planner, assets[2])
    _add_file(planner, assets[2])
    _archive_file(planner, assets[3])
    _move_between_roots(planner, assets[4])
    _slow_copy_pair(planner, assets[5])


def _emit_media_rewrite_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _reencode_video(planner, assets[0])
    _reencode_audio(planner, assets[1])
    _remux_container(planner, assets[2])
    _edit_metadata(planner, assets[3])


def _emit_sidecar_subtitle_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    subtitle_asset = _first_declared_subtitle_asset(assets)
    _create_subtitle_sidecar(planner, subtitle_asset)
    _embed_latest_subtitle_sidecar(planner)
    _extract_subtitle(planner, subtitle_asset)
    _remove_first_sidecar(planner)
    _create_nfo_sidecar(planner, assets[1])
    _update_first_sidecar(planner)


def _emit_malformed_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _corrupt_container_header(planner, assets[0])
    _truncate_file(planner, assets[1])
    _corrupt_packet_range(planner, assets[2])
    _write_invalid_duration_metadata(planner, assets[3])


def _emit_network_lag_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _network_lag_pair(planner, assets[0], NetworkLagEffect.DELAYED_VISIBILITY)
    _network_lag_pair(planner, assets[1], NetworkLagEffect.DELAYED_RENAME)
    _network_lag_pair(planner, assets[2], NetworkLagEffect.HELD_HANDLE)


def _emit_tv_topology_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _renumber_episode(planner, target="episode_001", episode_number=2)
    _move_episode_to_season(
        planner,
        target="episode_001",
        to_season="season_002",
        episode_number=2,
    )
    _rename_file(planner, assets[0])
    _reencode_video(planner, assets[0])


def _emit_music_topology_required_events(planner: TimelinePlanner) -> None:
    assets = planner.assets
    _renumber_disc(planner, target="disc_001", disc_number=2)
    _move_track_to_disc(
        planner,
        target="track_002",
        to_disc="disc_002",
        track_number=2,
    )
    _rename_file(planner, assets[0])
    _reencode_audio(planner, assets[1])


def _emit_negative_oracle_required_events(planner: TimelinePlanner) -> None:
    _wrong_oracle_hash(planner, planner.assets[0])


def _emit_filesystem_artifact_required_events(planner: TimelinePlanner) -> None:
    _touch_mtime(planner, planner.assets[0])


def _fill_remaining_events(
    *,
    planner: TimelinePlanner,
    config: LaneConfig,
    rng: RngStream,
) -> None:
    stable_assets = [
        asset for asset in planner.assets if asset.asset_id not in planner.media_unstable_assets
    ]
    if stable_assets:
        filler_actions = (_move_asset, _rename_file, _edit_metadata, _create_nfo_sidecar)
    else:
        filler_actions = (_move_asset, _rename_file, _create_nfo_sidecar)
    while len(planner.events) < config.timeline_events:
        # Roughly 1-in-4 filler events update an existing sidecar (when any
        # live sidecar exists) rather than emitting a move/rename/nfo event.
        if _has_live_sidecars(planner) and rng.randint(0, 3) == 0:
            _update_first_sidecar(planner)
            continue
        action = rng.choice(filler_actions)
        asset_pool = stable_assets if action is _edit_metadata else planner.assets
        action(planner, rng.choice(asset_pool))


def _move_asset(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.MoveAssetEvent(
            id=planner.event_id("move"),
            at=planner.at(),
            target=asset.asset_id,
            to=(
                f"{planner.root_path}/fuzz/"
                f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
            ),
        )
    )


def _rename_file(planner: TimelinePlanner, asset: PlannedAsset) -> EventReference:
    event_id = planner.event_id("rename")
    at = planner.at()
    event = scenario_contract.RenameFileEvent(
        id=event_id,
        at=at,
        target=asset.asset_id,
        to=(
            f"{planner.root_path}/renamed/"
            f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
        ),
    )
    planner.append_event(event)
    return EventReference(event_id=event_id, at=at)


def _delete_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.DeleteFileEvent(
            id=planner.event_id("delete"),
            at=planner.at(),
            target=asset.asset_id,
        )
    )


def _add_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.AddFileEvent(
            id=planner.event_id("add"),
            at=planner.at(),
            target=asset.asset_id,
            to=(
                f"{planner.root_path}/restored/"
                f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
            ),
        )
    )


def _archive_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.ArchiveFileEvent(
            id=planner.event_id("archive"),
            at=planner.at(),
            target=asset.asset_id,
        )
    )


def _move_between_roots(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.MoveBetweenRootsEvent(
            id=planner.event_id("move_between_roots"),
            at=planner.at(),
            target=asset.asset_id,
            from_root_id=planner.root_id,
            to_root_id=planner.secondary_root_id,
        )
    )


def _slow_copy_pair(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    start_index = planner.next_index()
    start_id = planner.event_id("slow_copy_start")
    planner.append_event(
        scenario_contract.SlowCopyStartEvent(
            id=start_id,
            at=f"{start_index}ns",
            target=asset.asset_id,
            to=f"{planner.root_path}/fuzz/{asset.asset_id}-slow.{asset.container}",
            temp_path=f"{planner.root_path}/fuzz/.{asset.asset_id}-slow.tmp",
            duration="1ns",
        )
    )
    planner.append_event(
        scenario_contract.SlowCopyCommitEvent(
            id=planner.event_id("slow_copy_commit"),
            at=f"{start_index + 1}ns",
            for_=start_id,
        )
    )


def _renumber_episode(
    planner: TimelinePlanner,
    *,
    target: str,
    episode_number: int,
) -> None:
    planner.append_event(
        scenario_contract.RenumberEpisodeEvent(
            id=planner.event_id("renumber_episode"),
            at=planner.at(),
            target=target,
            episode_number=episode_number,
        )
    )


def _move_episode_to_season(
    planner: TimelinePlanner,
    *,
    target: str,
    to_season: str,
    episode_number: int,
) -> None:
    planner.append_event(
        scenario_contract.MoveEpisodeToSeasonEvent(
            id=planner.event_id("move_episode_to_season"),
            at=planner.at(),
            target=target,
            to_season=to_season,
            episode_number=episode_number,
        )
    )


def _renumber_disc(
    planner: TimelinePlanner,
    *,
    target: str,
    disc_number: int,
) -> None:
    planner.append_event(
        scenario_contract.RenumberDiscEvent(
            id=planner.event_id("renumber_disc"),
            at=planner.at(),
            target=target,
            disc_number=disc_number,
        )
    )


def _move_track_to_disc(
    planner: TimelinePlanner,
    *,
    target: str,
    to_disc: str,
    track_number: int,
) -> None:
    planner.append_event(
        scenario_contract.MoveTrackToDiscEvent(
            id=planner.event_id("move_track_to_disc"),
            at=planner.at(),
            target=target,
            to_disc=to_disc,
            track_number=track_number,
        )
    )


def _reencode_video(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    if asset.resolution is None:
        raise ValueError(f"reencode_video requires a video asset, got {asset.asset_id}")
    resolution = "1080p" if asset.resolution != "1080p" else "hd"
    planner.append_event(
        scenario_contract.ReencodeVideoEvent(
            id=planner.event_id("reencode_video"),
            at=planner.at(),
            target=asset.asset_id,
            resolution=resolution,
            codec="h264",
        )
    )


def _reencode_audio(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    to_channels = "stereo" if asset.audio_channels != "stereo" else "mono"
    planner.append_event(
        scenario_contract.ReencodeAudioEvent(
            id=planner.event_id("reencode_audio"),
            at=planner.at(),
            target=asset.asset_id,
            from_channels=scenario_contract.AudioChannelLayout(asset.audio_channels),
            to_channels=scenario_contract.AudioChannelLayout(to_channels),
        )
    )


def _remux_container(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    to_container = "mp4" if asset.container != "mp4" else "mkv"
    planner.append_event(
        scenario_contract.RemuxContainerEvent(
            id=planner.event_id("remux"),
            at=planner.at(),
            target=asset.asset_id,
            to_container=to_container,
        )
    )


def _corrupt_container_header(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.CorruptContainerHeaderEvent(
            id=planner.event_id("corrupt_header"),
            at=planner.at(),
            target=asset.asset_id,
            bytes=CORRUPT_HEADER_BYTES,
        )
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _truncate_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.TruncateFileEvent(
            id=planner.event_id("truncate"),
            at=planner.at(),
            target=asset.asset_id,
            keep_bytes=TRUNCATE_KEEP_BYTES,
        )
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _corrupt_packet_range(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.CorruptPacketRangeEvent(
            id=planner.event_id("packet_corrupt"),
            at=planner.at(),
            target=asset.asset_id,
            stream=scenario_contract.PacketStreamKind.VIDEO,
            packet_start=0,
            packet_count=1,
        )
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _write_invalid_duration_metadata(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.WriteInvalidDurationMetadataEvent(
            id=planner.event_id("invalid_duration"),
            at=planner.at(),
            target=asset.asset_id,
            value="not-a-duration",
        )
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _wrong_oracle_hash(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.WrongOracleHashEvent(
            id=planner.event_id("wrong_hash"),
            at=planner.at(),
            target=asset.asset_id,
        )
    )


def _touch_mtime(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.append_event(
        scenario_contract.TouchMtimeEvent(
            id=planner.event_id("touch_mtime"),
            at=planner.at(),
            target=asset.asset_id,
            offset="2s",
        )
    )


def _network_lag_pair(
    planner: TimelinePlanner,
    asset: PlannedAsset,
    effect: NetworkLagEffect,
) -> None:
    if effect is NetworkLagEffect.DELAYED_RENAME:
        trigger = _rename_file(planner, asset)
    else:
        trigger = _edit_metadata(planner, asset)

    start_id = planner.event_id("network_lag_start")
    planner.append_event(
        scenario_contract.NetworkLagStartEvent(
            id=start_id,
            at=trigger.at,
            effect=effect,
            target=asset.asset_id,
            after=trigger.event_id,
            duration="1ns",
        )
    )
    planner.append_event(
        scenario_contract.NetworkLagCommitEvent(
            id=planner.event_id("network_lag_commit"),
            at=_one_ns_after(trigger.at),
            for_=start_id,
        )
    )


def _one_ns_after(at: str) -> str:
    if not at.endswith("ns"):
        raise ValueError(f"expected ns timestamp, got {at!r}")
    return f"{int(at.removesuffix('ns')) + 1}ns"


def _edit_metadata(planner: TimelinePlanner, asset: PlannedAsset) -> EventReference:
    event_id = planner.event_id("metadata")
    at = planner.at()
    event = scenario_contract.EditMetadataEvent(
        id=event_id,
        at=at,
        target=asset.asset_id,
        fields={"title": f"Generated Title {planner.next_index():04d}"},
    )
    planner.append_event(event)
    return EventReference(event_id=event_id, at=at)


def _create_nfo_sidecar(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    path = f"{planner.root_path}/sidecars/{asset.asset_id}-{planner.next_index():04d}.nfo"
    planner.append_event(
        scenario_contract.CreateSidecarEvent(
            id=planner.event_id("create_nfo"),
            at=planner.at(),
            target=asset.asset_id,
            to=path,
            kind=SidecarKind.NFO,
        )
    )
    planner.sidecars_by_asset.setdefault(asset.asset_id, []).append((SidecarKind.NFO.value, path))


def _create_subtitle_sidecar(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    path = f"{planner.root_path}/sidecars/{asset.asset_id}-{planner.next_index():04d}.srt"
    planner.append_event(
        scenario_contract.CreateSidecarEvent(
            id=planner.event_id("create_subtitle"),
            at=planner.at(),
            target=asset.asset_id,
            to=path,
            kind=SidecarKind.SUBTITLE,
            language="eng",
        )
    )
    planner.sidecars_by_asset.setdefault(asset.asset_id, []).append(
        (SidecarKind.SUBTITLE.value, path)
    )


def _extract_subtitle(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    path = f"{planner.root_path}/sidecars/{asset.asset_id}-{planner.next_index():04d}.srt"
    planner.append_event(
        scenario_contract.ExtractSubtitleEvent(
            id=planner.event_id("extract_subtitle"),
            at=planner.at(),
            target=asset.asset_id,
            to=path,
            language="eng",
        )
    )
    planner.sidecars_by_asset.setdefault(asset.asset_id, []).append(
        (SidecarKind.SUBTITLE.value, path)
    )


def _first_declared_subtitle_asset(assets: list[PlannedAsset]) -> PlannedAsset:
    for asset in assets:
        if asset.has_declared_subtitle:
            return asset
    raise ValueError("lane requires at least one asset with declared subtitles")


def _update_first_sidecar(planner: TimelinePlanner) -> None:
    for asset_id, sidecars in planner.sidecars_by_asset.items():
        if not sidecars:
            continue
        _, path = sidecars[0]
        planner.append_event(
            scenario_contract.UpdateSidecarEvent(
                id=planner.event_id("update_sidecar"),
                at=planner.at(),
                target=asset_id,
                sidecar_path=path,
            )
        )
        return
    raise ValueError("update_sidecar requires a live sidecar")


def _remove_first_sidecar(planner: TimelinePlanner) -> None:
    for asset_id, sidecars in tuple(planner.sidecars_by_asset.items()):
        if not sidecars:
            continue
        _, path = sidecars.pop(0)
        if not sidecars:
            del planner.sidecars_by_asset[asset_id]
        planner.append_event(
            scenario_contract.RemoveSidecarEvent(
                id=planner.event_id("remove_sidecar"),
                at=planner.at(),
                target=asset_id,
                sidecar_path=path,
            )
        )
        return
    raise ValueError("remove_sidecar requires a live sidecar")


def _embed_latest_subtitle_sidecar(planner: TimelinePlanner) -> None:
    for asset_id, sidecars in reversed(tuple(planner.sidecars_by_asset.items())):
        for index in range(len(sidecars) - 1, -1, -1):
            kind, path = sidecars[index]
            if kind != SidecarKind.SUBTITLE.value:
                continue
            sidecars.pop(index)
            if not sidecars:
                del planner.sidecars_by_asset[asset_id]
            planner.append_event(
                scenario_contract.EmbedSubtitleEvent(
                    id=planner.event_id("embed_subtitle"),
                    at=planner.at(),
                    target=asset_id,
                    sidecar_path=path,
                )
            )
            return
    raise ValueError("lane requires a live subtitle sidecar")


def _has_live_sidecars(planner: TimelinePlanner) -> bool:
    return any(planner.sidecars_by_asset.values())


def _lane_config(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    movies: int = 0,
    series: int = 0,
    artists: int = 0,
    timeline_events: int,
    required_cells: frozenset[str],
    required_events: Callable[[TimelinePlanner], None],
) -> LaneConfig:
    """Build a lane config, deriving its gated profiles from required cells.

    ``profiles`` is derived from ``required_cells`` via
    :func:`~chaos_librarian.generation.lanes.derive_required_profiles` rather
    than hand-listed, so a lane's declared profiles cannot drift from the
    profile-gated actions it actually generates.
    """
    return LaneConfig(
        profile=profile,
        lane=lane,
        profiles=derive_required_profiles(profile, required_cells),
        movies=movies,
        series=series,
        artists=artists,
        timeline_events=timeline_events,
        required_cells=required_cells,
        required_events=required_events,
    )


LANE_CONFIGS: Final[dict[tuple[FuzzProfileName, FuzzLaneName], LaneConfig]] = {
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE): _lane_config(
        profile=FuzzProfileName.FUZZ_SMOKE,
        lane=FuzzLaneName.SMOKE,
        movies=3,
        timeline_events=12,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.MOVE_ASSET),
                action_cell(TimelineActionName.RENAME_FILE),
                action_cell(TimelineActionName.EDIT_METADATA),
                action_cell(TimelineActionName.CREATE_SIDECAR),
                action_cell(TimelineActionName.UPDATE_SIDECAR),
            }
        ),
        required_events=_emit_smoke_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        movies=10,
        timeline_events=32,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.MOVE_ASSET),
                action_cell(TimelineActionName.RENAME_FILE),
                action_cell(TimelineActionName.DELETE_FILE),
                action_cell(TimelineActionName.ADD_FILE),
                action_cell(TimelineActionName.ARCHIVE_FILE),
                action_cell(TimelineActionName.MOVE_BETWEEN_ROOTS),
                action_cell(TimelineActionName.SLOW_COPY_START),
                action_cell(TimelineActionName.SLOW_COPY_COMMIT),
            }
        ),
        required_events=_emit_core_fs_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MEDIA_REWRITE,
        movies=10,
        timeline_events=32,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.REENCODE_VIDEO),
                action_cell(TimelineActionName.REENCODE_AUDIO),
                action_cell(TimelineActionName.REMUX_CONTAINER),
                action_cell(TimelineActionName.EDIT_METADATA),
            }
        ),
        required_events=_emit_media_rewrite_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.SIDECAR_SUBTITLE,
        movies=10,
        timeline_events=32,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.CREATE_SIDECAR),
                action_cell(TimelineActionName.UPDATE_SIDECAR),
                action_cell(TimelineActionName.REMOVE_SIDECAR),
                action_cell(TimelineActionName.EXTRACT_SUBTITLE),
                action_cell(TimelineActionName.EMBED_SUBTITLE),
                CELL_SIDE_SUBTITLE,
                CELL_SIDE_NFO_OR_POSTER,
            }
        ),
        required_events=_emit_sidecar_subtitle_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
        movies=10,
        timeline_events=24,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.CORRUPT_CONTAINER_HEADER),
                action_cell(TimelineActionName.TRUNCATE_FILE),
                action_cell(TimelineActionName.CORRUPT_PACKET_RANGE),
                action_cell(TimelineActionName.WRITE_INVALID_DURATION_METADATA),
            }
        ),
        required_events=_emit_malformed_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NEGATIVE_ORACLE): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.NEGATIVE_ORACLE,
        movies=8,
        timeline_events=16,
        required_cells=frozenset({action_cell(TimelineActionName.WRONG_ORACLE_HASH)}),
        required_events=_emit_negative_oracle_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.FILESYSTEM_ARTIFACT): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.FILESYSTEM_ARTIFACT,
        movies=8,
        timeline_events=16,
        required_cells=frozenset({action_cell(TimelineActionName.TOUCH_MTIME)}),
        required_events=_emit_filesystem_artifact_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NETWORK_LAG): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.NETWORK_LAG,
        movies=8,
        timeline_events=18,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.NETWORK_LAG_START),
                action_cell(TimelineActionName.NETWORK_LAG_COMMIT),
                f"{CELL_LAG_EFFECT_PREFIX}{NetworkLagEffect.DELAYED_VISIBILITY.value}",
                f"{CELL_LAG_EFFECT_PREFIX}{NetworkLagEffect.DELAYED_RENAME.value}",
                f"{CELL_LAG_EFFECT_PREFIX}{NetworkLagEffect.HELD_HANDLE.value}",
            }
        ),
        required_events=_emit_network_lag_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.TV_TOPOLOGY): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.TV_TOPOLOGY,
        series=1,
        timeline_events=18,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.RENUMBER_EPISODE),
                action_cell(TimelineActionName.MOVE_EPISODE_TO_SEASON),
                action_cell(TimelineActionName.RENAME_FILE),
                action_cell(TimelineActionName.REENCODE_VIDEO),
            }
        ),
        required_events=_emit_tv_topology_required_events,
    ),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MUSIC_TOPOLOGY): _lane_config(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MUSIC_TOPOLOGY,
        artists=1,
        timeline_events=18,
        required_cells=frozenset(
            {
                action_cell(TimelineActionName.RENUMBER_DISC),
                action_cell(TimelineActionName.MOVE_TRACK_TO_DISC),
                action_cell(TimelineActionName.RENAME_FILE),
                action_cell(TimelineActionName.REENCODE_AUDIO),
            }
        ),
        required_events=_emit_music_topology_required_events,
    ),
}


def lane_config_for(profile: FuzzProfileName, lane: FuzzLaneName) -> LaneConfig:
    config = LANE_CONFIGS.get((profile, lane))
    if config is None:
        raise ValueError(f"lane {lane.value} is not valid for {profile.value}")
    return config
