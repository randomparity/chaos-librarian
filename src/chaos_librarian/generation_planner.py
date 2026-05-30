"""Content and timeline planning for deterministic fuzz generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import NetworkLagEffect, SidecarKind
from chaos_librarian.generation_lanes import LaneConfig

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
    events: list[dict[str, object]] = field(default_factory=list)
    sidecars_by_asset: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    media_unstable_assets: set[str] = field(default_factory=set)

    def next_index(self) -> int:
        return len(self.events) + 1

    def event_id(self, prefix: str) -> str:
        return f"fuzz_{self.next_index():04d}_{prefix}"

    def at(self) -> str:
        return f"{self.next_index()}ns"


def plan_payload_parts(
    *,
    seed: int,
    config: LaneConfig,
    rng: Any,
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
    _emit_lane_required_events(planner=planner, lane=config.lane)
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
        planner.events,
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
    rng: Any,
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
    rng: Any,
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
    rng: Any,
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
                            "id": "disc_002",
                            "disc_number": 3,
                            "tracks": [],
                        },
                    ],
                }
            ],
        }
    ]


def _asset_payload(asset: PlannedAsset, rng: Any) -> dict[str, object]:
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


def _emit_lane_required_events(
    *,
    planner: TimelinePlanner,
    lane: FuzzLaneName,
) -> None:
    if lane is FuzzLaneName.SMOKE:
        _emit_smoke_required_events(planner)
    elif lane is FuzzLaneName.CORE_FS:
        _emit_core_fs_required_events(planner)
    elif lane is FuzzLaneName.MEDIA_REWRITE:
        _emit_media_rewrite_required_events(planner)
    elif lane is FuzzLaneName.SIDECAR_SUBTITLE:
        _emit_sidecar_subtitle_required_events(planner)
    elif lane is FuzzLaneName.MALFORMED:
        _emit_malformed_required_events(planner)
    elif lane is FuzzLaneName.NEGATIVE_ORACLE:
        _wrong_oracle_hash(planner, planner.assets[0])
    elif lane is FuzzLaneName.FILESYSTEM_ARTIFACT:
        _touch_mtime(planner, planner.assets[0])
    elif lane is FuzzLaneName.NETWORK_LAG:
        _emit_network_lag_required_events(planner)
    elif lane is FuzzLaneName.TV_TOPOLOGY:
        _emit_tv_topology_required_events(planner)
    elif lane is FuzzLaneName.MUSIC_TOPOLOGY:
        _emit_music_topology_required_events(planner)
    else:
        raise ValueError(f"unsupported fuzz lane {lane.value}")


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


def _fill_remaining_events(
    *,
    planner: TimelinePlanner,
    config: LaneConfig,
    rng: Any,
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
    planner.events.append(
        {
            "id": planner.event_id("move"),
            "at": planner.at(),
            "action": "move_asset",
            "target": asset.asset_id,
            "to": (
                f"{planner.root_path}/fuzz/"
                f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
            ),
        }
    )


def _rename_file(planner: TimelinePlanner, asset: PlannedAsset) -> EventReference:
    event_id = planner.event_id("rename")
    at = planner.at()
    event: dict[str, object] = {
        "id": event_id,
        "at": at,
        "action": "rename_file",
        "target": asset.asset_id,
        "to": (
            f"{planner.root_path}/renamed/"
            f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
        ),
    }
    planner.events.append(event)
    return EventReference(event_id=event_id, at=at)


def _delete_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("delete"),
            "at": planner.at(),
            "action": "delete_file",
            "target": asset.asset_id,
        }
    )


def _add_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("add"),
            "at": planner.at(),
            "action": "add_file",
            "target": asset.asset_id,
            "to": (
                f"{planner.root_path}/restored/"
                f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
            ),
        }
    )


def _archive_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("archive"),
            "at": planner.at(),
            "action": "archive_file",
            "target": asset.asset_id,
        }
    )


def _move_between_roots(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("move_between_roots"),
            "at": planner.at(),
            "action": "move_between_roots",
            "target": asset.asset_id,
            "from_root_id": planner.root_id,
            "to_root_id": planner.secondary_root_id,
        }
    )


def _slow_copy_pair(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    start_index = planner.next_index()
    start_id = planner.event_id("slow_copy_start")
    planner.events.append(
        {
            "id": start_id,
            "at": f"{start_index}ns",
            "action": "slow_copy_start",
            "target": asset.asset_id,
            "to": f"{planner.root_path}/fuzz/{asset.asset_id}-slow.{asset.container}",
            "temp_path": f"{planner.root_path}/fuzz/.{asset.asset_id}-slow.tmp",
            "duration": "1ns",
        }
    )
    planner.events.append(
        {
            "id": planner.event_id("slow_copy_commit"),
            "at": f"{start_index + 1}ns",
            "action": "slow_copy_commit",
            "for": start_id,
        }
    )


def _renumber_episode(
    planner: TimelinePlanner,
    *,
    target: str,
    episode_number: int,
) -> None:
    planner.events.append(
        {
            "id": planner.event_id("renumber_episode"),
            "at": planner.at(),
            "action": "renumber_episode",
            "target": target,
            "episode_number": episode_number,
        }
    )


def _move_episode_to_season(
    planner: TimelinePlanner,
    *,
    target: str,
    to_season: str,
    episode_number: int,
) -> None:
    planner.events.append(
        {
            "id": planner.event_id("move_episode_to_season"),
            "at": planner.at(),
            "action": "move_episode_to_season",
            "target": target,
            "to_season": to_season,
            "episode_number": episode_number,
        }
    )


def _renumber_disc(
    planner: TimelinePlanner,
    *,
    target: str,
    disc_number: int,
) -> None:
    planner.events.append(
        {
            "id": planner.event_id("renumber_disc"),
            "at": planner.at(),
            "action": "renumber_disc",
            "target": target,
            "disc_number": disc_number,
        }
    )


def _move_track_to_disc(
    planner: TimelinePlanner,
    *,
    target: str,
    to_disc: str,
    track_number: int,
) -> None:
    planner.events.append(
        {
            "id": planner.event_id("move_track_to_disc"),
            "at": planner.at(),
            "action": "move_track_to_disc",
            "target": target,
            "to_disc": to_disc,
            "track_number": track_number,
        }
    )


def _reencode_video(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    if asset.resolution is None:
        raise ValueError(f"reencode_video requires a video asset, got {asset.asset_id}")
    resolution = "1080p" if asset.resolution != "1080p" else "hd"
    planner.events.append(
        {
            "id": planner.event_id("reencode_video"),
            "at": planner.at(),
            "action": "reencode_video",
            "target": asset.asset_id,
            "resolution": resolution,
            "codec": "h264",
        }
    )


def _reencode_audio(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    to_channels = "stereo" if asset.audio_channels != "stereo" else "mono"
    planner.events.append(
        {
            "id": planner.event_id("reencode_audio"),
            "at": planner.at(),
            "action": "reencode_audio",
            "target": asset.asset_id,
            "from_channels": asset.audio_channels,
            "to_channels": to_channels,
        }
    )


def _remux_container(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    to_container = "mp4" if asset.container != "mp4" else "mkv"
    planner.events.append(
        {
            "id": planner.event_id("remux"),
            "at": planner.at(),
            "action": "remux_container",
            "target": asset.asset_id,
            "to_container": to_container,
        }
    )


def _corrupt_container_header(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("corrupt_header"),
            "at": planner.at(),
            "action": "corrupt_container_header",
            "target": asset.asset_id,
            "bytes": CORRUPT_HEADER_BYTES,
        }
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _truncate_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("truncate"),
            "at": planner.at(),
            "action": "truncate_file",
            "target": asset.asset_id,
            "keep_bytes": TRUNCATE_KEEP_BYTES,
        }
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _corrupt_packet_range(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("packet_corrupt"),
            "at": planner.at(),
            "action": "corrupt_packet_range",
            "target": asset.asset_id,
            "stream": "video",
            "packet_start": 0,
            "packet_count": 1,
        }
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _write_invalid_duration_metadata(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("invalid_duration"),
            "at": planner.at(),
            "action": "write_invalid_duration_metadata",
            "target": asset.asset_id,
            "value": "not-a-duration",
        }
    )
    planner.media_unstable_assets.add(asset.asset_id)


def _wrong_oracle_hash(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("wrong_hash"),
            "at": planner.at(),
            "action": "wrong_oracle_hash",
            "target": asset.asset_id,
        }
    )


def _touch_mtime(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("touch_mtime"),
            "at": planner.at(),
            "action": "touch_mtime",
            "target": asset.asset_id,
            "offset": "2s",
        }
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
    planner.events.append(
        {
            "id": start_id,
            "at": trigger.at,
            "action": "network_lag_start",
            "effect": effect.value,
            "target": asset.asset_id,
            "after": trigger.event_id,
            "duration": "1ns",
        }
    )
    planner.events.append(
        {
            "id": planner.event_id("network_lag_commit"),
            "at": _one_ns_after(trigger.at),
            "action": "network_lag_commit",
            "for": start_id,
        }
    )


def _one_ns_after(at: str) -> str:
    if not at.endswith("ns"):
        raise ValueError(f"expected ns timestamp, got {at!r}")
    return f"{int(at.removesuffix('ns')) + 1}ns"


def _edit_metadata(planner: TimelinePlanner, asset: PlannedAsset) -> EventReference:
    event_id = planner.event_id("metadata")
    at = planner.at()
    event: dict[str, object] = {
        "id": event_id,
        "at": at,
        "action": "edit_metadata",
        "target": asset.asset_id,
        "fields": {"title": f"Generated Title {planner.next_index():04d}"},
    }
    planner.events.append(event)
    return EventReference(event_id=event_id, at=at)


def _create_nfo_sidecar(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    path = f"{planner.root_path}/sidecars/{asset.asset_id}-{planner.next_index():04d}.nfo"
    planner.events.append(
        {
            "id": planner.event_id("create_nfo"),
            "at": planner.at(),
            "action": "create_sidecar",
            "target": asset.asset_id,
            "to": path,
            "kind": SidecarKind.NFO.value,
        }
    )
    planner.sidecars_by_asset.setdefault(asset.asset_id, []).append((SidecarKind.NFO.value, path))


def _create_subtitle_sidecar(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    path = f"{planner.root_path}/sidecars/{asset.asset_id}-{planner.next_index():04d}.srt"
    planner.events.append(
        {
            "id": planner.event_id("create_subtitle"),
            "at": planner.at(),
            "action": "create_sidecar",
            "target": asset.asset_id,
            "to": path,
            "kind": SidecarKind.SUBTITLE.value,
            "language": "eng",
        }
    )
    planner.sidecars_by_asset.setdefault(asset.asset_id, []).append(
        (SidecarKind.SUBTITLE.value, path)
    )


def _extract_subtitle(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    path = f"{planner.root_path}/sidecars/{asset.asset_id}-{planner.next_index():04d}.srt"
    planner.events.append(
        {
            "id": planner.event_id("extract_subtitle"),
            "at": planner.at(),
            "action": "extract_subtitle",
            "target": asset.asset_id,
            "to": path,
            "language": "eng",
        }
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
        planner.events.append(
            {
                "id": planner.event_id("update_sidecar"),
                "at": planner.at(),
                "action": "update_sidecar",
                "target": asset_id,
                "sidecar_path": path,
            }
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
        planner.events.append(
            {
                "id": planner.event_id("remove_sidecar"),
                "at": planner.at(),
                "action": "remove_sidecar",
                "target": asset_id,
                "sidecar_path": path,
            }
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
            planner.events.append(
                {
                    "id": planner.event_id("embed_subtitle"),
                    "at": planner.at(),
                    "action": "embed_subtitle",
                    "target": asset_id,
                    "sidecar_path": path,
                }
            )
            return
    raise ValueError("lane requires a live subtitle sidecar")


def _has_live_sidecars(planner: TimelinePlanner) -> bool:
    return any(planner.sidecars_by_asset.values())
