"""Content and timeline planning for deterministic fuzz generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.generation_lanes import LaneConfig


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    asset_id: str
    container: str
    video_codec: str
    resolution: str
    audio_channels: str
    has_embedded_subtitle: bool = False


@dataclass(slots=True)
class TimelinePlanner:
    root_id: str
    root_path: str
    secondary_root_id: str
    assets: list[PlannedAsset]
    events: list[dict[str, object]] = field(default_factory=list)
    placed_assets: set[str] = field(default_factory=set)
    sidecars_by_asset: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    deleted_assets: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.placed_assets = {asset.asset_id for asset in self.assets}

    def next_index(self) -> int:
        return len(self.events) + 1

    def event_id(self, prefix: str) -> str:
        return f"fuzz_{self.next_index():04d}_{prefix}"

    def at(self) -> str:
        return f"{self.next_index()}ns"


def plan_payload_parts(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
    config: LaneConfig,
    rng: Any,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    assets = _planned_assets(config=config)
    library = _library_for_lane(lane)
    planner = TimelinePlanner(
        root_id="movies-hd",
        root_path="movies-hd",
        secondary_root_id="cold-storage",
        assets=assets,
    )
    _emit_lane_required_events(planner=planner, lane=lane, rng=rng)
    _fill_remaining_events(planner=planner, config=config, rng=rng)
    return (
        library,
        _works_payload(profile=profile, lane=lane, seed=seed, assets=assets, rng=rng),
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
                has_embedded_subtitle=index % 3 == 0,
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
    if asset.has_embedded_subtitle:
        payload["subtitles"] = [
            {
                "source": "generated_srt",
                "codec": "srt",
                "language": "eng",
                "mode": "embedded",
            }
        ]
    return payload


def _emit_lane_required_events(
    *,
    planner: TimelinePlanner,
    lane: FuzzLaneName,
    rng: Any,
) -> None:
    del rng
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
        _create_subtitle_sidecar(planner, assets[0])
        _update_first_sidecar(planner)
        _remove_first_sidecar(planner)
        _create_nfo_sidecar(planner, assets[1])
        _extract_subtitle(planner, _first_embedded_subtitle_asset(assets))
        _embed_latest_subtitle_sidecar(planner)


def _fill_remaining_events(
    *,
    planner: TimelinePlanner,
    config: LaneConfig,
    rng: Any,
) -> None:
    safe_actions = (_move_asset, _rename_file, _edit_metadata, _create_nfo_sidecar)
    while len(planner.events) < config.timeline_events:
        if planner.sidecars_by_asset and rng.randint(0, 3) == 0:
            _update_first_sidecar(planner)
            continue
        action = rng.choice(safe_actions)
        action(planner, rng.choice(planner.assets))


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


def _rename_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("rename"),
            "at": planner.at(),
            "action": "rename_file",
            "target": asset.asset_id,
            "to": (
                f"{planner.root_path}/renamed/"
                f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
            ),
        }
    )


def _delete_file(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("delete"),
            "at": planner.at(),
            "action": "delete_file",
            "target": asset.asset_id,
        }
    )
    planner.deleted_assets.add(asset.asset_id)
    planner.placed_assets.discard(asset.asset_id)


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
    planner.deleted_assets.discard(asset.asset_id)
    planner.placed_assets.add(asset.asset_id)


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


def _edit_metadata(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("metadata"),
            "at": planner.at(),
            "action": "edit_metadata",
            "target": asset.asset_id,
            "fields": {"title": f"Generated Title {planner.next_index():04d}"},
        }
    )


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


def _first_embedded_subtitle_asset(assets: list[PlannedAsset]) -> PlannedAsset:
    for asset in assets:
        if asset.has_embedded_subtitle:
            return asset
    raise ValueError("lane requires at least one asset with embedded subtitles")


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


def _remove_first_sidecar(planner: TimelinePlanner) -> None:
    for asset_id, sidecars in planner.sidecars_by_asset.items():
        if not sidecars:
            continue
        _, path = sidecars.pop(0)
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


def _embed_latest_subtitle_sidecar(planner: TimelinePlanner) -> None:
    for asset_id, sidecars in reversed(planner.sidecars_by_asset.items()):
        for index in range(len(sidecars) - 1, -1, -1):
            kind, path = sidecars[index]
            if kind != SidecarKind.SUBTITLE.value:
                continue
            sidecars.pop(index)
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
