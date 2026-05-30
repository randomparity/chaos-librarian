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

from ruamel.yaml import YAML

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.profiles import (
    CANONICAL_FUZZ_LANES,
    FuzzLaneName,
    FuzzProfileName,
)
from chaos_librarian.contract.scenario import (
    FUZZ_GENERATION_PROFILE_VERSION,
    Scenario,
    generation_budget_for,
)
from chaos_librarian.determinism.rng import RngStreams
from chaos_librarian.determinism.trace import TraceRecorder
from chaos_librarian.generation_lanes import coverage_for_payload
from chaos_librarian.generation_planner import lane_config_for, plan_payload_parts
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation


@dataclass(frozen=True, slots=True)
class GeneratedScenario:
    """Generated scenario bytes paired with the validated scenario model."""

    data: bytes
    scenario: Scenario


@dataclass(frozen=True, slots=True)
class BatchItem:
    """One unit of batch work: the lane and seed for a single scenario."""

    lane: FuzzLaneName
    seed: int


def scenario_id_for(profile: FuzzProfileName, lane: FuzzLaneName, seed: int) -> str:
    """Return the canonical ``scenario_id`` for a generated fuzz scenario.

    Single source of truth shared by the generator and the batch path planner so
    file names and the ``scenario_id`` embedded in the YAML cannot drift.
    """
    return f"{profile.value}-{lane.value}-seed-{seed}"


def plan_generation_batch(
    profile: FuzzProfileName,
    lane: FuzzLaneName | None,
    seed: int,
    count: int,
) -> tuple[BatchItem, ...]:
    """Return the deterministic ``(lane, seed)`` work-list for a batch.

    ``seed_i = seed + i``. When ``lane`` is ``None`` the lanes cycle the canonical
    order for the profile; otherwise every item uses ``lane``.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    if lane is None:
        order = CANONICAL_FUZZ_LANES[profile]
        return tuple(BatchItem(lane=order[i % len(order)], seed=seed + i) for i in range(count))
    return tuple(BatchItem(lane=lane, seed=seed + i) for i in range(count))


class GeneratedScenarioCoverageError(ValueError):
    """Raised when generated YAML does not satisfy the selected lane contract."""


class GeneratedScenarioValidationError(ValueError):
    """Raised when generated YAML fails the full validation pipeline."""


def generate_scenario_yaml(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None = None,
) -> bytes:
    """Return deterministic scenario YAML bytes for one fuzz profile, lane, and seed."""
    return generate_scenario(profile=profile, seed=seed, lane=lane).data


def generate_scenario(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None = None,
) -> GeneratedScenario:
    """Return deterministic scenario YAML and its validated model."""
    if seed < 0:
        raise ValueError("seed must be non-negative")

    data = _generate_scenario_yaml_unvalidated(profile=profile, seed=seed, lane=lane)
    scenario = _validate_generated_yaml(data)
    return GeneratedScenario(data=data, scenario=scenario)


def _generate_scenario_yaml_unvalidated(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None,
) -> bytes:
    resolved_lane = lane or FuzzLaneName.SMOKE
    config = lane_config_for(profile=profile, lane=resolved_lane)
    rng = RngStreams(resolved_seed=seed, recorder=TraceRecorder()).stream("fuzz-generation")
    library, movies, series, artists, timeline = plan_payload_parts(
        seed=seed,
        config=config,
        rng=rng,
    )
    payload: dict[str, object] = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": scenario_id_for(profile, resolved_lane, seed),
        "seed": seed,
        "duration_scale": "short",
        "profiles": [label.value for label in config.profiles],
        "generation": {
            "generator": "chaos-librarian",
            "profile": profile.value,
            "lane": resolved_lane.value,
            "profile_version": FUZZ_GENERATION_PROFILE_VERSION,
            "seed": seed,
            "budgets": generation_budget_for(profile).model_dump(mode="json"),
        },
        "library": library,
        "movies": movies,
        "series": series,
        "artists": artists,
        "timeline": timeline,
    }
    coverage = coverage_for_payload(payload)
    missing = coverage.missing_required_cells(config.required_cells)
    if missing:
        missing_sorted = ", ".join(sorted(missing))
        raise GeneratedScenarioCoverageError(
            f"missing required coverage for {profile.value}/{resolved_lane.value} "
            f"seed {seed}: {missing_sorted}"
        )
    data = _dump_yaml(payload)
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
    *,
    scenario: Scenario | None = None,
) -> str:
    """Return sorted JSON for the successful generate command."""
    if scenario is None:
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


def _dump_yaml(payload: Mapping[str, object]) -> bytes:
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    stream = io.StringIO()
    yaml.dump(payload, stream)
    return stream.getvalue().encode()


def _validate_generated_yaml(data: bytes) -> Scenario:
    run_input = prepare_run_input_from_bytes(raw_bytes=data, source_label="<generated>")
    report = run_validation(run_input)
    if not report.ok:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise GeneratedScenarioValidationError(f"generated scenario failed validation: {issues}")
    return run_input.scenario
