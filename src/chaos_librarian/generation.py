"""Deterministic fuzz scenario generation."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import (
    FUZZ_GENERATION_PROFILE_VERSION,
    Scenario,
    generation_budget_for,
)
from chaos_librarian.determinism.rng import RngStreams
from chaos_librarian.determinism.trace import TraceRecorder
from chaos_librarian.generation_lanes import LaneConfig, lane_config_for, profiles_for_lane
from chaos_librarian.scenario_io import parse_scenario_bytes


@dataclass(frozen=True, slots=True)
class _GeneratedAsset:
    asset_id: str
    container: str


_VIDEO_SOURCES: Final[tuple[str, ...]] = ("color_bars", "mandelbrot", "solid_color")
_RESOLUTIONS: Final[tuple[str, ...]] = ("sd", "hd", "1080p")
_AUDIO_SOURCES: Final[tuple[str, ...]] = ("sine", "silence", "channel_tones")
_AUDIO_CHANNELS: Final[tuple[str, ...]] = ("mono", "stereo", "5.1")
_CONTAINERS: Final[tuple[str, ...]] = ("mkv", "mp4")


def generate_scenario_yaml(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None = None,
) -> bytes:
    """Return deterministic scenario YAML bytes for one fuzz profile, lane, and seed."""
    if seed < 0:
        raise ValueError("seed must be non-negative")

    resolved_lane = lane or FuzzLaneName.SMOKE
    config = lane_config_for(profile=profile, lane=resolved_lane)
    profile_labels = profiles_for_lane(profile=profile, lane=resolved_lane)
    rng = RngStreams(resolved_seed=seed, recorder=TraceRecorder()).stream("fuzz-generation")
    assets, works = _generate_works(profile=profile, seed=seed, config=config, rng=rng)
    payload: dict[str, object] = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": f"{profile.value}-{resolved_lane.value}-seed-{seed}",
        "seed": seed,
        "duration_scale": "short",
        "profiles": [label.value for label in profile_labels],
        "generation": {
            "generator": "chaos-librarian",
            "profile": profile.value,
            "lane": resolved_lane.value,
            "profile_version": FUZZ_GENERATION_PROFILE_VERSION,
            "seed": seed,
            "budgets": generation_budget_for(profile).model_dump(mode="json"),
        },
        "library": {"roots": [{"id": "movies_hd", "path": "movies-hd"}]},
        "works": works,
        "timeline": _generate_timeline(config=config, assets=assets, rng=rng),
    }
    data = _dump_yaml(payload)
    _validate_generated_yaml(data)
    return data


def write_generated_scenario(out: Path, data: bytes) -> None:
    """Atomically write generated scenario bytes without overwriting ``out``."""
    if out.exists():
        raise FileExistsError(out)
    if not out.parent.exists():
        raise FileNotFoundError(out.parent)
    if not out.parent.is_dir():
        raise NotADirectoryError(out.parent)

    fd, temp_name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, out)
    finally:
        temp_path.unlink(missing_ok=True)


def generated_scenario_summary(
    out: Path,
    data: bytes,
) -> str:
    """Return sorted JSON for the successful generate command."""
    scenario = _validate_generated_yaml(data)
    if scenario.generation is None:
        raise ValueError("generated scenario is missing generation metadata")
    summary = {
        "ok": True,
        "lane": scenario.generation.lane.value,
        "profile": scenario.generation.profile.value,
        "scenario_id": scenario.scenario_id,
        "scenario_path": str(out.resolve()),
        "seed": scenario.generation.seed,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    return json.dumps(summary, sort_keys=True)


def _generate_works(
    *,
    profile: FuzzProfileName,
    seed: int,
    config: LaneConfig,
    rng,
) -> tuple[list[_GeneratedAsset], list[dict[str, object]]]:
    assets: list[_GeneratedAsset] = []
    works: list[dict[str, object]] = []
    for index in range(1, config.works + 1):
        asset = _GeneratedAsset(
            asset_id=f"asset_{index:03d}",
            container=rng.choice(_CONTAINERS),
        )
        assets.append(asset)
        works.append(_work_payload(index=index, profile=profile, seed=seed, asset=asset, rng=rng))
    return assets, works


def _work_payload(
    *,
    index: int,
    profile: FuzzProfileName,
    seed: int,
    asset: _GeneratedAsset,
    rng,
) -> dict[str, object]:
    return {
        "id": f"work_{index:03d}",
        "title": f"{profile.value} Work {seed}-{index:03d}",
        "variants": [
            {
                "id": f"variant_{index:03d}",
                "label": "generated",
                "bundle": {
                    "id": f"bundle_{index:03d}",
                    "assets": [_asset_payload(asset=asset, rng=rng)],
                },
            }
        ],
    }


def _asset_payload(asset: _GeneratedAsset, rng) -> dict[str, object]:
    return {
        "id": asset.asset_id,
        "role": "primary_video",
        "container": asset.container,
        "duration_seconds": rng.randint(2, 8),
        "video": {
            "source": rng.choice(_VIDEO_SOURCES),
            "codec": "h264",
            "resolution": rng.choice(_RESOLUTIONS),
        },
        "audio": [
            {
                "source": rng.choice(_AUDIO_SOURCES),
                "codec": "aac",
                "channels": rng.choice(_AUDIO_CHANNELS),
                "language": "eng",
            }
        ],
    }


def _generate_timeline(
    *,
    config: LaneConfig,
    assets: list[_GeneratedAsset],
    rng,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    sidecars: list[tuple[str, str]] = []
    for index in range(1, config.timeline_events + 1):
        asset = rng.choice(assets)
        actions = ["move_asset", "rename_file", "edit_metadata", "create_sidecar"]
        if sidecars:
            actions.append("update_sidecar")
        action = rng.choice(actions)
        events.append(_event_payload(index=index, action=action, asset=asset, sidecars=sidecars))
    return events


def _event_payload(
    *,
    index: int,
    action: str,
    asset: _GeneratedAsset,
    sidecars: list[tuple[str, str]],
) -> dict[str, object]:
    event_id = f"fuzz_{index:04d}"
    base: dict[str, object] = {
        "id": event_id,
        "at": f"{index}ns",
        "action": action,
        "target": asset.asset_id,
    }
    if action in {"move_asset", "rename_file"}:
        base["to"] = f"movies-hd/fuzz/{asset.asset_id}-{index:04d}.{asset.container}"
    elif action == "edit_metadata":
        base["fields"] = {"title": f"Generated Title {index:04d}"}
    elif action == "create_sidecar":
        path = f"movies-hd/fuzz/{asset.asset_id}-{index:04d}.nfo"
        sidecars.append((asset.asset_id, path))
        base["to"] = path
        base["kind"] = "nfo"
    elif action == "update_sidecar":
        target, path = sidecars[index % len(sidecars)]
        base["target"] = target
        base["sidecar_path"] = path
    return base


def _dump_yaml(payload: Mapping[str, object]) -> bytes:
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    stream = io.StringIO()
    yaml.dump(payload, stream)
    return stream.getvalue().encode()


def _validate_generated_yaml(data: bytes) -> Scenario:
    raw, _ = parse_scenario_bytes(data, source=Path("<generated>"))
    return Scenario.model_validate(raw)
