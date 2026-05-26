"""Content and timeline planning for deterministic fuzz generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import NetworkLagEffect, SidecarKind
from chaos_librarian.generation_lanes import LaneConfig


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    asset_id: str
    container: str
    video_codec: str
    resolution: str
    audio_channels: str
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
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    assets = _planned_assets(config=config)
    library = _library_for_lane(config.lane)
    planner = TimelinePlanner(
        root_id="movies-hd",
        root_path="movies-hd",
        secondary_root_id="cold-storage",
        assets=assets,
    )
    _emit_lane_required_events(planner=planner, lane=config.lane)
    _fill_remaining_events(planner=planner, config=config, rng=rng)
    return (
        library,
        _works_payload(
            profile=config.profile,
            lane=config.lane,
            seed=seed,
            assets=assets,
            rng=rng,
        ),
        planner.events,
    )


def _library_for_lane(lane: FuzzLaneName) -> dict[str, object]:
    roots: list[dict[str, str]] = [{"id": "movies-hd", "path": "movies-hd"}]
    library: dict[str, object] = {"roots": roots}
    if lane is FuzzLaneName.CORE_FS:
        roots.append({"id": "cold-storage", "path": "cold-storage"})
        library["archive_root"] = "cold-storage"
    return library


def _planned_assets(*, config: LaneConfig) -> list[PlannedAsset]:
    containers = ("mkv", "mp4")
    resolutions = ("sd", "hd", "1080p")
    channels = ("mono", "stereo", "5.1")
    assets: list[PlannedAsset] = []
    for index in range(1, config.works + 1):
        assets.append(
            PlannedAsset(
                asset_id=f"asset_{index:03d}",
                container=containers[(index - 1) % len(containers)],
                video_codec="hevc" if index % 5 == 0 else "h264",
                resolution=resolutions[(index - 1) % len(resolutions)],
                audio_channels=channels[(index - 1) % len(channels)],
                has_declared_subtitle=(
                    index % 3 == 0 or (config.lane is FuzzLaneName.SIDECAR_SUBTITLE and index == 1)
                ),
            )
        )
    return assets


def _works_payload(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
    assets: list[PlannedAsset],
    rng: Any,
) -> list[dict[str, object]]:
    works: list[dict[str, object]] = []
    for index, asset in enumerate(assets, start=1):
        works.append(
            {
                "id": f"work_{index:03d}",
                "title": f"{profile.value} {lane.value} Work {seed}-{index:03d}",
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
    return works


def _asset_payload(asset: PlannedAsset, rng: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": asset.asset_id,
        "role": "primary_video",
        "container": asset.container,
        "duration_seconds": rng.randint(2, 8),
        "video": {
            "source": "color_bars",
            "codec": asset.video_codec,
            "resolution": asset.resolution,
        },
        "audio": [
            {
                "source": "sine",
                "codec": "aac",
                "channels": asset.audio_channels,
                "language": "eng",
            }
        ],
    }
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
    assets = planner.assets
    if lane is FuzzLaneName.SMOKE:
        _move_asset(planner, assets[0])
        _rename_file(planner, assets[1])
        _edit_metadata(planner, assets[0])
        _create_nfo_sidecar(planner, assets[0])
        _update_first_sidecar(planner)
    elif lane is FuzzLaneName.CORE_FS:
        _move_asset(planner, assets[0])
        _rename_file(planner, assets[1])
        _delete_file(planner, assets[2])
        _add_file(planner, assets[2])
        _archive_file(planner, assets[3])
        _move_between_roots(planner, assets[4])
        _slow_copy_pair(planner, assets[5])
    elif lane is FuzzLaneName.MEDIA_REWRITE:
        _reencode_video(planner, assets[0])
        _reencode_audio(planner, assets[1])
        _remux_container(planner, assets[2])
        _edit_metadata(planner, assets[3])
    elif lane is FuzzLaneName.SIDECAR_SUBTITLE:
        subtitle_asset = _first_declared_subtitle_asset(assets)
        _create_subtitle_sidecar(planner, subtitle_asset)
        _embed_latest_subtitle_sidecar(planner)
        _extract_subtitle(planner, subtitle_asset)
        _remove_first_sidecar(planner)
        _create_nfo_sidecar(planner, assets[1])
        _update_first_sidecar(planner)
    elif lane is FuzzLaneName.MALFORMED:
        _corrupt_container_header(planner, assets[0])
        _truncate_file(planner, assets[1])
        _corrupt_packet_range(planner, assets[2])
        _write_invalid_duration_metadata(planner, assets[3])
    elif lane is FuzzLaneName.NEGATIVE_ORACLE:
        _wrong_oracle_hash(planner, assets[0])
    elif lane is FuzzLaneName.FILESYSTEM_ARTIFACT:
        _touch_mtime(planner, assets[0])
    elif lane is FuzzLaneName.NETWORK_LAG:
        _network_lag_pair(planner, assets[0], NetworkLagEffect.DELAYED_VISIBILITY)
        _network_lag_pair(planner, assets[1], NetworkLagEffect.DELAYED_RENAME)
        _network_lag_pair(planner, assets[2], NetworkLagEffect.HELD_HANDLE)
    else:
        raise ValueError(f"unsupported fuzz lane {lane.value}")


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


def _reencode_video(planner: TimelinePlanner, asset: PlannedAsset) -> None:
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
            "bytes": 64,
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
            "keep_bytes": 4096,
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
