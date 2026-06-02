"""Shared validation, preflight, and plan setup for materializer modes."""

from __future__ import annotations

import enum
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine.plan import (
    PlanArtifacts,
    PlanExecutionRequest,
    run_materializer_plan,
)
from chaos_librarian.engine.resolution import ResolvedEvent, resolve_timeline
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer.errors import CapabilityGateError, ScenarioValidationError
from chaos_librarian.materializer.preparation.capability_gates import (
    assert_capable_for_audio_recipes,
    assert_capable_for_hdr_video,
    assert_capable_for_matroska_muxing_profiles,
    assert_capable_for_resolution_switch_video,
    assert_capable_for_webm_video,
)
from chaos_librarian.materializer.preparation.preflight import (
    iter_assets,
    preflight_asset,
    preflight_timeline,
)
from chaos_librarian.materializer.tooling.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.media_matrix import HEVC_VIDEO_CODECS
from chaos_librarian.topology import iter_asset_contexts
from chaos_librarian.validation import RunInput, run_validation
from chaos_librarian.validation.input import prepare_run_input

__all__ = [
    "MaterializerPreparationMode",
    "MaterializerPreparationRequest",
    "MaterializerReplayOverrides",
    "PreparedMaterializerRun",
    "prepare_materializer_run",
    "prepare_materializer_run_input",
]


class MaterializerPreparationMode(enum.StrEnum):
    """Execution mode whose policy controls materializer preparation."""

    MATERIALIZE = "materialize"
    WALL_CLOCK = "wall_clock"
    RUN_REPLAY = "run_replay"


@dataclass(frozen=True)
class MaterializerReplayOverrides:
    """Replay identity and journal-prefix overrides for run replay preparation."""

    resolved_seed: int
    run_id: uuid.UUID
    applied_events: int


@dataclass(frozen=True)
class MaterializerPreparationRequest:
    """Materializer preparation input plus the concrete execution mode policy."""

    run_input: RunInput
    mode: MaterializerPreparationMode
    validation_report: ValidationReport | None = None
    replay: MaterializerReplayOverrides | None = None
    resolved_timeline_check: Callable[[list[ResolvedEvent]], None] | None = None


@dataclass(frozen=True)
class PreparedMaterializerRun:
    """Validated scenario inputs shared by materialize and wall-clock run."""

    run_input: RunInput
    validation_report: ValidationReport
    scenario: Scenario
    caps: Capabilities
    run_id: uuid.UUID
    plan_artifacts: PlanArtifacts


@dataclass(frozen=True)
class _PreparationModePolicy:
    validation_failure_message: str
    validation_payload_exclude_none: bool
    allow_network_lag: bool
    allow_network_fs_chaos: bool
    check_hevc_video: bool


_PREPARATION_MODE_POLICIES: Final = {
    MaterializerPreparationMode.MATERIALIZE: _PreparationModePolicy(
        validation_failure_message="scenario failed semantic validation; refusing to materialize",
        validation_payload_exclude_none=True,
        allow_network_lag=False,
        allow_network_fs_chaos=False,
        check_hevc_video=True,
    ),
    MaterializerPreparationMode.WALL_CLOCK: _PreparationModePolicy(
        validation_failure_message="scenario failed semantic validation; refusing to run",
        validation_payload_exclude_none=False,
        allow_network_lag=True,
        allow_network_fs_chaos=True,
        check_hevc_video=False,
    ),
    MaterializerPreparationMode.RUN_REPLAY: _PreparationModePolicy(
        validation_failure_message="run replay scenario re-validation failed",
        validation_payload_exclude_none=True,
        allow_network_lag=True,
        allow_network_fs_chaos=True,
        check_hevc_video=False,
    ),
}


def prepare_materializer_run(
    scenario_path: Path,
    *,
    mode: MaterializerPreparationMode,
    resolved_timeline_check: Callable[[list[ResolvedEvent]], None] | None = None,
) -> PreparedMaterializerRun:
    """Validate, preflight, gate, and plan a materializer scenario.

    Args:
        scenario_path: Scenario YAML file to prepare.
        mode: Materializer execution mode whose policy should be applied.
        resolved_timeline_check: Optional mode-specific check that runs after
            timeline preflight and before capability/tool detection.

    Returns:
        Shared materializer inputs, including the full plan artifacts.

    Raises:
        ScenarioLoadError: ``scenario_path`` cannot be read or parsed.
        ScenarioValidationError: scenario fails shape or semantic validation.
        TimelineUnsupportedError: the timeline contains an unsupported action.
        CapabilityGateError: required materialization capabilities are missing.
    """
    run_input = prepare_run_input(scenario_path)
    return prepare_materializer_run_input(
        MaterializerPreparationRequest(
            run_input=run_input,
            mode=mode,
            resolved_timeline_check=resolved_timeline_check,
        )
    )


def prepare_materializer_run_input(
    request: MaterializerPreparationRequest,
) -> PreparedMaterializerRun:
    """Validate, preflight, gate, and plan an already-loaded materializer request.

    Args:
        request: Parsed input plus the preparation mode and optional replay
            metadata.

    Returns:
        Shared materializer inputs, including the planned artifact prefix.

    Raises:
        ScenarioValidationError: scenario fails semantic validation.
        TimelineUnsupportedError: the timeline contains an unsupported action.
        CapabilityGateError: required materialization capabilities are missing.
    """
    _validate_preparation_request(request)
    validation_report = request.validation_report or run_validation(request.run_input)
    policy = _PREPARATION_MODE_POLICIES[request.mode]

    if not validation_report.ok:
        raise ScenarioValidationError(
            policy.validation_failure_message,
            payload={
                "validation_report": validation_report.model_dump(
                    mode="json",
                    exclude_none=policy.validation_payload_exclude_none,
                ),
            },
            validation_report=validation_report,
        )
    scenario = request.run_input.scenario
    preflight_timeline(
        scenario,
        allow_network_lag=policy.allow_network_lag,
        allow_network_fs_chaos=policy.allow_network_fs_chaos,
    )
    if request.resolved_timeline_check is not None:
        request.resolved_timeline_check(resolve_timeline(scenario))
    caps = detect_capabilities()
    _assert_capabilities(scenario, caps, check_hevc_video=policy.check_hevc_video)
    run_id = _prepared_run_id(request)
    plan_artifacts = run_materializer_plan(
        _plan_execution_request(
            request=request,
            validation_report=validation_report,
            run_id=run_id,
        )
    )
    _preflight_assets(scenario)
    return PreparedMaterializerRun(
        run_input=request.run_input,
        validation_report=validation_report,
        scenario=scenario,
        caps=caps,
        run_id=run_id,
        plan_artifacts=plan_artifacts,
    )


def _validate_preparation_request(request: MaterializerPreparationRequest) -> None:
    if request.mode is MaterializerPreparationMode.RUN_REPLAY:
        if request.replay is not None:
            return
        raise ChaosLibrarianValueError("run replay preparation requires replay overrides")
    if request.replay is not None:
        raise ChaosLibrarianValueError(
            f"{request.mode.value} preparation must not include replay overrides"
        )


def _prepared_run_id(request: MaterializerPreparationRequest) -> uuid.UUID:
    if request.replay is not None:
        return request.replay.run_id
    return uuid.uuid4()


def _plan_execution_request(
    *,
    request: MaterializerPreparationRequest,
    validation_report: ValidationReport,
    run_id: uuid.UUID,
) -> PlanExecutionRequest:
    replay = request.replay
    return PlanExecutionRequest(
        run_input=request.run_input,
        validation_report=validation_report,
        resolved_seed_override=replay.resolved_seed if replay is not None else None,
        run_id_override=run_id,
        applied_events_override=replay.applied_events if replay is not None else None,
    )


def _assert_capabilities(
    scenario: Scenario,
    caps: Capabilities,
    *,
    check_hevc_video: bool,
) -> None:
    assert_capable_for_static_materialize(caps)
    assert_capable_for_matroska_muxing_profiles(scenario, caps)
    assert_capable_for_webm_video(scenario, caps)
    assert_capable_for_audio_recipes(scenario, caps)
    assert_capable_for_resolution_switch_video(scenario, caps)
    if check_hevc_video:
        _assert_capable_for_hevc_video(scenario, caps)
    assert_capable_for_hdr_video(scenario, caps)


def _assert_capable_for_hevc_video(scenario: Scenario, caps: Capabilities) -> None:
    """Raise before run-dir allocation when scenario needs HEVC and libx265 is absent."""
    for asset in iter_assets(scenario):
        if asset.video is None or asset.video.codec not in HEVC_VIDEO_CODECS:
            continue
        if caps.ready_for.materialize_hevc_video:
            return
        raise CapabilityGateError(
            "HEVC/H.265 video materialization requires FFmpeg with the libx265 encoder",
            asset_id=asset.id,
            field="ready_for.materialize_hevc_video",
            payload={
                "capability": "ready_for.materialize_hevc_video",
                "required_encoder": "libx265",
                "video_codec": asset.video.codec,
            },
        )


def _preflight_assets(scenario: Scenario) -> None:
    for context in iter_asset_contexts(scenario):
        asset = context.asset
        preflight_asset(
            parent_kind=context.parent_kind,
            video=asset.video,
            audios=asset.audio,
            subtitles=asset.subtitles,
            container=asset.container,
        )
