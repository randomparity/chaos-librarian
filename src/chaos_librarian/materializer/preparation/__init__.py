"""Shared validation, preflight, and plan setup for materializer modes."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine.plan import (
    PlanArtifacts,
    PlanExecutionRequest,
    run_materializer_plan,
)
from chaos_librarian.engine.resolution import ResolvedEvent, resolve_timeline
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
    "PreparedMaterializerRun",
    "prepare_materializer_run",
    "prepare_materializer_run_input",
    "prepare_validated_materializer_run_input",
]


@dataclass(frozen=True)
class PreparedMaterializerRun:
    """Validated scenario inputs shared by materialize and wall-clock run."""

    run_input: RunInput
    validation_report: ValidationReport
    scenario: Scenario
    caps: Capabilities
    run_id: uuid.UUID
    plan_artifacts: PlanArtifacts


def prepare_materializer_run(
    scenario_path: Path,
    *,
    validation_failure_message: str,
    validation_payload_exclude_none: bool,
    allow_network_lag: bool = False,
    allow_network_fs_chaos: bool = False,
    check_hevc_video: bool = False,
    resolved_timeline_check: Callable[[list[ResolvedEvent]], None] | None = None,
) -> PreparedMaterializerRun:
    """Validate, preflight, gate, and plan a materializer scenario.

    Args:
        scenario_path: Scenario YAML file to prepare.
        validation_failure_message: Mode-specific validation error message.
        validation_payload_exclude_none: Whether the embedded validation
            report payload should omit ``None`` values.
        allow_network_lag: Allow wall-clock-only network lag timeline actions.
        allow_network_fs_chaos: Allow wall-clock-only network filesystem chaos
            timeline actions.
        check_hevc_video: Require the legacy materialize HEVC encoder gate.
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
        run_input,
        validation_failure_message=validation_failure_message,
        validation_payload_exclude_none=validation_payload_exclude_none,
        allow_network_lag=allow_network_lag,
        allow_network_fs_chaos=allow_network_fs_chaos,
        check_hevc_video=check_hevc_video,
        resolved_timeline_check=resolved_timeline_check,
    )


def prepare_materializer_run_input(
    run_input: RunInput,
    *,
    validation_failure_message: str,
    validation_payload_exclude_none: bool,
    allow_network_lag: bool = False,
    allow_network_fs_chaos: bool = False,
    check_hevc_video: bool = False,
    resolved_timeline_check: Callable[[list[ResolvedEvent]], None] | None = None,
    resolved_seed_override: int | None = None,
    run_id_override: uuid.UUID | None = None,
    applied_events_override: int | None = None,
) -> PreparedMaterializerRun:
    """Validate, preflight, gate, and plan an already-loaded materializer input.

    Args:
        run_input: Parsed scenario bytes and model from the caller's boundary.
        validation_failure_message: Mode-specific validation error message.
        validation_payload_exclude_none: Whether the embedded validation
            report payload should omit ``None`` values.
        allow_network_lag: Allow wall-clock-only network lag timeline actions.
        allow_network_fs_chaos: Allow wall-clock-only network filesystem chaos
            timeline actions.
        check_hevc_video: Require the legacy materialize HEVC encoder gate.
        resolved_timeline_check: Optional mode-specific check that runs after
            timeline preflight and before capability/tool detection.
        resolved_seed_override: Optional plan seed override for replayed runs.
        run_id_override: Optional run id override for replayed runs.
        applied_events_override: Optional raw event prefix for replayed runs.

    Returns:
        Shared materializer inputs, including the planned artifact prefix.

    Raises:
        ScenarioValidationError: scenario fails semantic validation.
        TimelineUnsupportedError: the timeline contains an unsupported action.
        CapabilityGateError: required materialization capabilities are missing.
    """
    validation_report = run_validation(run_input)
    return prepare_validated_materializer_run_input(
        run_input=run_input,
        validation_report=validation_report,
        validation_failure_message=validation_failure_message,
        validation_payload_exclude_none=validation_payload_exclude_none,
        allow_network_lag=allow_network_lag,
        allow_network_fs_chaos=allow_network_fs_chaos,
        check_hevc_video=check_hevc_video,
        resolved_timeline_check=resolved_timeline_check,
        resolved_seed_override=resolved_seed_override,
        run_id_override=run_id_override,
        applied_events_override=applied_events_override,
    )


def prepare_validated_materializer_run_input(
    *,
    run_input: RunInput,
    validation_report: ValidationReport,
    validation_failure_message: str,
    validation_payload_exclude_none: bool,
    allow_network_lag: bool = False,
    allow_network_fs_chaos: bool = False,
    check_hevc_video: bool = False,
    resolved_timeline_check: Callable[[list[ResolvedEvent]], None] | None = None,
    resolved_seed_override: int | None = None,
    run_id_override: uuid.UUID | None = None,
    applied_events_override: int | None = None,
) -> PreparedMaterializerRun:
    """Preflight, gate, and plan an already-validated materializer input.

    Args:
        run_input: Parsed scenario bytes and model from the caller's boundary.
        validation_report: Validation report already produced for ``run_input``.
        validation_failure_message: Mode-specific validation error message.
        validation_payload_exclude_none: Whether the embedded validation
            report payload should omit ``None`` values.
        allow_network_lag: Allow wall-clock-only network lag timeline actions.
        allow_network_fs_chaos: Allow wall-clock-only network filesystem chaos
            timeline actions.
        check_hevc_video: Require the legacy materialize HEVC encoder gate.
        resolved_timeline_check: Optional mode-specific check that runs after
            timeline preflight and before capability/tool detection.
        resolved_seed_override: Optional plan seed override for replayed runs.
        run_id_override: Optional run id override for replayed runs.
        applied_events_override: Optional raw event prefix for replayed runs.

    Returns:
        Shared materializer inputs, including the planned artifact prefix.

    Raises:
        ScenarioValidationError: scenario fails semantic validation.
        TimelineUnsupportedError: the timeline contains an unsupported action.
        CapabilityGateError: required materialization capabilities are missing.
    """
    if not validation_report.ok:
        raise ScenarioValidationError(
            validation_failure_message,
            payload={
                "validation_report": validation_report.model_dump(
                    mode="json",
                    exclude_none=validation_payload_exclude_none,
                ),
            },
            validation_report=validation_report,
        )
    scenario = run_input.scenario
    preflight_timeline(
        scenario,
        allow_network_lag=allow_network_lag,
        allow_network_fs_chaos=allow_network_fs_chaos,
    )
    if resolved_timeline_check is not None:
        resolved_timeline_check(resolve_timeline(scenario))
    caps = detect_capabilities()
    _assert_capabilities(scenario, caps, check_hevc_video=check_hevc_video)
    run_id = run_id_override or uuid.uuid4()
    plan_artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=run_input,
            validation_report=validation_report,
            resolved_seed_override=resolved_seed_override,
            run_id_override=run_id,
            applied_events_override=applied_events_override,
        )
    )
    _preflight_assets(scenario)
    return PreparedMaterializerRun(
        run_input=run_input,
        validation_report=validation_report,
        scenario=scenario,
        caps=caps,
        run_id=run_id,
        plan_artifacts=plan_artifacts,
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
