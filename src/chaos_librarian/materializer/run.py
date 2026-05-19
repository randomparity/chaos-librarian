"""Materialize orchestrator — the 8-step pipeline.

Steps 1-5 run entirely in memory; step 6 is the only filesystem-touching
primitive before synthesis. The materializer raises the spec's error
hierarchy on any failure; the CLI handler converts them to exit codes.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
)
from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.manifest import Manifest, ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import (
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    MaterializeReplayBundle,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import (
    Asset,
    AudioSource,
    AudioTrack,
    Scenario,
    SubtitleSource,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.engine import PlanArtifacts, run_plan
from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    MaterializationError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.ffmpeg import build_command, run_ffmpeg
from chaos_librarian.materializer.probe import probe_file
from chaos_librarian.materializer.recipes import (
    FFmpegInput,
    recipe_channel_tones,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_silence,
    recipe_sine,
    recipe_solid_color,
    srt_payload,
)
from chaos_librarian.materializer.writer import (
    MaterializeMetadata,
    MaterializeReports,
    begin_materialize_run,
    cleanup_failed_run,
    finalize_materialize_run,
)
from chaos_librarian.validation import RunInput, run_validation
from chaos_librarian.validation.input import prepare_run_input

_RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}
_FPS_DEFAULT: Final = 24

_VIDEO_RECIPES = {
    VideoSource.MANDELBROT: recipe_mandelbrot,
    VideoSource.COLOR_BARS: recipe_color_bars,
    VideoSource.SOLID_COLOR: recipe_solid_color,
}
_AUDIO_RECIPES = {
    AudioSource.SINE: recipe_sine,
    AudioSource.SILENCE: recipe_silence,
    AudioSource.CHANNEL_TONES: recipe_channel_tones,
}

_CREATED_BY: Final = f"chaos-librarian/{_chaos_librarian_version}"


@dataclass(frozen=True, slots=True)
class MaterializeArtifacts:
    """Return value of ``materialize_scenario``."""

    current_manifest: Manifest
    materialization_report: MaterializationReport
    replay_bundle: MaterializeReplayBundle


@dataclass(frozen=True, slots=True)
class RunContext:
    """Per-run invariants set once at the top of ``materialize_scenario``.

    Threaded through synthesis/finalize/cleanup so each helper depends
    on a single immutable object instead of repeating the same 7-9
    kwargs (issue #12). The validation report lives on
    ``plan_artifacts.validation_report`` — no separate field here.
    """

    run_input: RunInput
    out_dir: Path
    run_id: uuid.UUID
    started_at: datetime
    caps: Capabilities
    plan_artifacts: PlanArtifacts


def materialize_scenario(scenario_path: Path, out_dir: Path) -> MaterializeArtifacts:
    """Run the 8-step pipeline. Raises on any failure (caught by the CLI)."""
    started_at = datetime.now(UTC)
    run_input = prepare_run_input(scenario_path)
    # Run semantic validation BEFORE the timeline scope check so
    # containment/lifecycle errors surface as ScenarioValidationError
    # (exit 3) instead of being shadowed by TimelineUnsupportedError when an
    # invalid scenario happens to also declare timeline events.
    validation_report = run_validation(run_input)
    if not validation_report.ok:
        raise ScenarioValidationError(
            "scenario failed semantic validation; refusing to materialize",
            payload={
                "validation_report": validation_report.model_dump(mode="json", exclude_none=True),
            },
            validation_report=validation_report,
        )
    # Validation succeeded → ``RunInput.scenario`` cache is primed by the
    # shape pass; access the cached parse instead of re-validating.
    scenario = run_input.scenario
    if scenario.timeline:
        raise TimelineUnsupportedError(
            "materialize accepts static scenarios only; remove timeline events.",
            field="timeline",
            payload={"event_count": len(scenario.timeline)},
        )
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    plan_artifacts = run_plan(
        run_input=run_input,
        validation_report=validation_report,
        steps_limit=0,
    )
    for asset in _iter_assets(scenario):
        _preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=uuid.uuid4(),
        started_at=started_at,
        caps=caps,
        plan_artifacts=plan_artifacts,
    )
    begin_materialize_run(ctx.out_dir, _build_sentinel(ctx, "in_progress"))
    return _run_synthesis(ctx, scenario)


def _build_sentinel(ctx: RunContext, state: Literal["in_progress", "complete"]) -> RunSentinel:
    """Construct a RunSentinel from the per-run invariants in ``ctx``.

    The fields shared by every sentinel (``run_id``, ``schema_version``,
    ``created_by``, ``created_at``) live on the context; ``state`` is the
    only per-call variable.
    """
    return RunSentinel(
        run_id=ctx.run_id,
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by=_CREATED_BY,
        created_at=ctx.started_at,
        state=state,
    )


def _run_synthesis(ctx: RunContext, scenario: Scenario) -> MaterializeArtifacts:
    """Steps 7-8: per-asset synthesis loop and finalize/cleanup."""
    invocations: list[ToolInvocation] = []
    materialized: list[MaterializedAsset] = []
    try:
        for invocation_index, asset in enumerate(_iter_assets(scenario)):
            invocation, materialized_asset, probed, sidecar_hashes = _materialize_one_asset(
                asset,
                ctx.plan_artifacts.replay_bundle.resolved_seed,
                ctx.out_dir,
                ctx.caps,
                invocation_index,
            )
            invocations.append(invocation)
            materialized.append(materialized_asset)
            _augment_manifest(
                ctx.plan_artifacts.current_manifest,
                asset,
                materialized_asset,
                probed,
                sidecar_hashes,
            )
    except (ToolFailedError, ProbeParseError) as exc:
        if isinstance(exc, ToolFailedError):
            invocations.append(exc.invocation)
        _finalize_failure(ctx, exc, Outcome.TOOL_FAILED, invocations, materialized)
        raise
    return _finalize_success(ctx, invocations, materialized)


def _finalize_success(
    ctx: RunContext,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
) -> MaterializeArtifacts:
    """Step 8 (success path) — atomic metadata write, sentinel flips to complete."""
    finished_at = datetime.now(UTC)
    materialization_report = _build_report(
        outcome=Outcome.SUCCESS,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[],
    )
    replay_bundle = _build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
    )
    finalize_materialize_run(
        ctx.out_dir,
        _build_metadata(
            ctx, materialization_report, replay_bundle, _build_sentinel(ctx, "complete")
        ),
        _build_reports(ctx.plan_artifacts),
    )
    return MaterializeArtifacts(
        current_manifest=ctx.plan_artifacts.current_manifest,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
    )


def _preflight_asset(
    video: VideoTrack | None,
    audios: Sequence[AudioTrack],
    subtitles: Sequence[SubtitleTrack],
    container: str,
) -> None:
    """Run build_command in a dry mode — raises UnsupportedMaterializationError fast.

    Subtitle checks are inline: only ``codec=srt, source=generated_srt,
    mode=sidecar`` is supported. Without these gates, ``mode=embedded`` or
    ``codec=ass`` would fall through and the materialize "success" would
    silently drop the requested subtitles.
    """
    if video is None:
        raise UnsupportedMaterializationError(
            "every asset must declare a video track.",
            field="video",
            payload={},
        )
    video_recipe = _VIDEO_RECIPES.get(video.source)
    if video_recipe is None:
        raise UnsupportedMaterializationError(
            f"video source {video.source!r} not supported",
            field="video.source",
            payload={"supported": sorted(s.value for s in _VIDEO_RECIPES)},
        )
    audio_inputs = _preflight_audio_inputs(audios)
    _preflight_subtitles(subtitles)
    width, height = _RESOLUTION_PIXELS.get(video.resolution, (1, 1))
    video_input = video_recipe(width=width, height=height, fps=_FPS_DEFAULT, duration_s=1.0, seed=0)
    build_command(
        video=video,
        video_input=video_input,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=Path(f"/tmp/preflight.{container}"),
    )


def _preflight_audio_inputs(audios: Sequence[AudioTrack]) -> list[FFmpegInput]:
    """Build the audio FFmpegInput list at preflight time, raising on unknown sources."""
    inputs: list[FFmpegInput] = []
    for audio in audios:
        recipe = _AUDIO_RECIPES.get(audio.source)
        if recipe is None:
            raise UnsupportedMaterializationError(
                f"audio source {audio.source!r} not supported",
                field="audio.source",
                payload={"supported": sorted(s.value for s in _AUDIO_RECIPES)},
            )
        inputs.append(recipe(channels=audio.channels, duration_s=1.0, seed=0))
    return inputs


def _preflight_subtitles(subtitles: Sequence[SubtitleTrack]) -> None:
    """Subtitle matrix: SRT + generated + sidecar only."""
    for index, sub in enumerate(subtitles):
        if sub.codec != "srt":
            raise UnsupportedMaterializationError(
                f"subtitle codec {sub.codec!r} not supported",
                field=f"subtitle[{index}].codec",
                payload={"supported": ["srt"]},
            )
        if sub.source is not SubtitleSource.GENERATED_SRT:
            raise UnsupportedMaterializationError(
                f"subtitle source {sub.source!r} not supported",
                field=f"subtitle[{index}].source",
                payload={"supported": [SubtitleSource.GENERATED_SRT.value]},
            )
        if sub.mode != "sidecar":
            raise UnsupportedMaterializationError(
                f"subtitle mode {sub.mode!r} not supported",
                field=f"subtitle[{index}].mode",
                payload={"supported": ["sidecar"]},
            )


def _iter_assets(scenario: Scenario):
    """Iterate all assets in scenario order."""
    for work in scenario.works:
        for variant in work.variants:
            yield from variant.bundle.assets


def _materialize_one_asset(
    asset: Asset,
    seed: int,
    out_dir: Path,
    caps: Capabilities,
    invocation_index: int,
) -> tuple[
    ToolInvocation,
    MaterializedAsset,
    ProbedMedia,
    dict[tuple[str, str], str],
]:
    """Synthesize one asset, returning everything ``_augment_manifest`` needs.

    Returns a 4-tuple of (ffmpeg invocation, materialized asset record,
    probed-media result for the produced file, sidecar hashes keyed by
    ``(asset_id, language)``). Returning probed lets the orchestrator
    avoid re-probing; returning sidecar_hashes lets ``_augment_manifest``
    populate ``ManifestSidecar.content_hash``.
    """
    if asset.video is None:
        raise UnsupportedMaterializationError(
            "every asset must declare a video track.",
            field="video",
            asset_id=asset.id,
            payload={},
        )
    library_dir = out_dir / "library"
    output_path = library_dir / f"{asset.id}.{asset.container}"
    width, height = _RESOLUTION_PIXELS[asset.video.resolution]
    video_recipe = _VIDEO_RECIPES[asset.video.source]
    video_input = video_recipe(
        width=width,
        height=height,
        fps=_FPS_DEFAULT,
        duration_s=asset.duration_seconds,
        seed=seed,
    )
    audio_inputs: list[FFmpegInput] = []
    for audio in asset.audio:
        recipe = _AUDIO_RECIPES[audio.source]
        audio_inputs.append(
            recipe(channels=audio.channels, duration_s=asset.duration_seconds, seed=seed)
        )
    argv = build_command(
        video=asset.video,
        video_input=video_input,
        audios=asset.audio,
        audio_inputs=audio_inputs,
        output_path=output_path,
    )
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=caps.ffmpeg.version or "unknown")
    if invocation.exit_code != 0:
        raise ToolFailedError(
            f"ffmpeg exit {invocation.exit_code} for asset {asset.id}",
            asset_id=asset.id,
            field=None,
            payload={
                "stderr_tail": stderr_tail,
                "exit_code": invocation.exit_code,
            },
            invocation=invocation,
        )
    sidecar_hashes = _write_sidecars(asset, library_dir, seed)
    probed = probe_file(output_path)
    with output_path.open("rb") as fh:
        content_hash = "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
    materialized_asset = MaterializedAsset(
        asset_id=asset.id,
        location_path=str(output_path.relative_to(out_dir)),
        content_hash=content_hash,
        size_bytes=probed.size_bytes,
        duration_seconds=probed.duration_seconds,
        invocation_index=invocation_index,
    )
    return invocation, materialized_asset, probed, sidecar_hashes


def _write_sidecars(asset: Asset, library_dir: Path, seed: int) -> dict[tuple[str, str], str]:
    """Write each declared SRT sidecar and return its sha256 hash.

    Preflight already rejected non-sidecar modes, so every subtitle here
    is sidecar; hash the bytes so ``_augment_manifest`` can populate
    ``ManifestSidecar.content_hash``.
    """
    sidecar_hashes: dict[tuple[str, str], str] = {}
    for sub in asset.subtitles:
        sidecar_path = library_dir / f"{asset.id}.{sub.language}.srt"
        body = srt_payload(language=sub.language, duration_s=asset.duration_seconds, seed=seed)
        sidecar_path.write_text(body)
        sidecar_hashes[(asset.id, sub.language)] = (
            "sha256:" + hashlib.sha256(body.encode()).hexdigest()
        )
    return sidecar_hashes


def _augment_manifest(
    manifest: Manifest,
    asset: Asset,
    materialized: MaterializedAsset,
    probed: ProbedMedia,
    sidecar_hashes: dict[tuple[str, str], str],
) -> None:
    """Stamp ``content_hash`` + ``probed`` onto the version record and
    append/update ``ManifestSidecar`` rows for materialized sidecars.

    The engine does not pre-populate sidecars from ``scenario.subtitles``
    (sidecars there are added only via ``create_sidecar`` timeline events).
    Materialize must reflect the materialized sidecars in the manifest so
    consumers see the bytes they were promised; we append one
    ``ManifestSidecar`` per materialized language with a deterministic id
    derived from the asset and language.

    ``probed`` is passed in by ``_materialize_one_asset`` (which already
    ran ffprobe on the absolute output path). Re-probing via
    ``probe_file(Path(materialized.location_path))`` would dispatch
    against a run-dir-relative string and either miss the file or resolve
    against an unrelated local ``library/`` from the CLI cwd.
    """
    for version in manifest.versions:
        if version.asset_id == asset.id:
            version.content_hash = materialized.content_hash
            version.probed = probed
            break
    for sub in asset.subtitles:
        key = (asset.id, sub.language)
        content_hash = sidecar_hashes.get(key)
        if content_hash is None:
            continue
        sidecar_path = f"library/{asset.id}.{sub.language}.srt"
        existing = _find_sidecar_for(manifest, asset.id, sub.language)
        if existing is None:
            manifest.sidecars.append(
                ManifestSidecar(
                    id=f"sidecar_{asset.id}_{sub.language}",
                    asset_id=asset.id,
                    kind=sub.codec,
                    path=sidecar_path,
                    language=sub.language,
                    content_hash=content_hash,
                )
            )
        else:
            existing.content_hash = content_hash


def _find_sidecar_for(manifest: Manifest, asset_id: str, language: str) -> ManifestSidecar | None:
    """Return the ``ManifestSidecar`` for ``(asset_id, language)``, or ``None``.

    Matches on the explicit ``language`` field (manifest v3+). The previous
    substring-match on ``sidecar.path`` (``language in path``) mis-resolved
    whenever one language tag appeared as a substring of another (e.g.
    looking up ``"en"`` would match a ``"library/x.eng.srt"`` row).
    Engine-created sidecars (via the ``create_sidecar`` event) currently
    carry ``language=None`` and are skipped here.
    """
    for sidecar in manifest.sidecars:
        if sidecar.asset_id == asset_id and sidecar.language == language:
            return sidecar
    return None


def _build_report(
    *,
    outcome: Outcome,
    run_id: uuid.UUID,
    caps: Capabilities,
    started_at: datetime,
    finished_at: datetime,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    failures: list[MaterializationFailure],
) -> MaterializationReport:
    return MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=run_id,
        outcome=outcome,
        platform=caps.platform,
        started_at=started_at,
        finished_at=finished_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
        invocations=invocations,
        materialized=materialized,
        failures=failures,
    )


def _build_replay_bundle(
    *,
    run_id: uuid.UUID,
    scenario_yaml_bytes: bytes,
    plan_artifacts: PlanArtifacts,
    caps: Capabilities,
    created_at: datetime,
) -> MaterializeReplayBundle:
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=scenario_yaml_bytes.decode("utf-8"),
        run_id=run_id,
        resolved_seed=plan_artifacts.replay_bundle.resolved_seed,
        journal_digest=plan_artifacts.replay_bundle.journal_digest,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=created_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
    )


def _finalize_failure(
    ctx: RunContext,
    exc: MaterializationError,
    outcome: Outcome,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
) -> None:
    """Assemble every metadata file ``cleanup_failed_run`` requires.

    The failed run-dir must remain readable by ``inspect`` and removable
    by ``clean``. Both commands hard-require ``replay.json``; ``inspect``
    additionally hard-requires ``manifest.current.json``. The un-augmented
    plan-only manifest from ``ctx.plan_artifacts`` is correct here —
    synthesis aborted, so no version has ``content_hash``/``probed``.
    """
    finished_at = datetime.now(UTC)
    invocation = getattr(exc, "invocation", None)
    exit_code = invocation.exit_code if invocation is not None else None
    failure = MaterializationFailure(
        asset_id=getattr(exc, "asset_id", None),
        stage="ffmpeg" if outcome is Outcome.TOOL_FAILED else "ffprobe",
        exit_code=exit_code,
        stderr_tail=str(exc.payload.get("stderr_tail", "")),
        invocation_index=(len(invocations) - 1) if invocations else None,
    )
    report = _build_report(
        outcome=outcome,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[failure],
    )
    replay_bundle = _build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
    )
    cleanup_failed_run(
        ctx.out_dir,
        _build_metadata(ctx, report, replay_bundle, _build_sentinel(ctx, "complete")),
    )


def _build_metadata(
    ctx: RunContext,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    sentinel: RunSentinel,
) -> MaterializeMetadata:
    """Assemble the shared writer payload (success and failure paths)."""
    return MaterializeMetadata(
        initial_manifest=ctx.plan_artifacts.initial_manifest,
        current_manifest=ctx.plan_artifacts.current_manifest,
        journal_entries=ctx.plan_artifacts.journal,
        validation_report=ctx.plan_artifacts.validation_report,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        sentinel=sentinel,
    )


def _build_reports(plan_artifacts: PlanArtifacts) -> MaterializeReports:
    """Convert the engine's tuple-of-reports into the writer's id→report dicts."""
    reports = plan_artifacts.reports
    return MaterializeReports(
        assets={r.asset_id: r for r in reports.assets},
        works={r.work_id: r for r in reports.works},
        variants={r.variant_id: r for r in reports.variants},
        bundles={r.bundle_id: r for r in reports.bundles},
    )
