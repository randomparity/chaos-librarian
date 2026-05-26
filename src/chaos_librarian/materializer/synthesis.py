"""Per-asset ffmpeg invocation, probe, and SRT sidecar emission.

These are the only filesystem-touching helpers in the materialize
pipeline (the writer flushes metadata, but ffmpeg and the sidecar writer
emit media bytes). Both functions raise ``MaterializationError``
subclasses on failure; the orchestrator in ``run.py`` converts them to
``MaterializationFailure`` records and routes them through the writer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.manifest import Manifest, ProbedMedia
from chaos_librarian.contract.materialization import MaterializedAsset, ToolInvocation
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    Asset,
    EpisodeNaming,
    MovieLayout,
    Scenario,
    SeriesLayout,
    TrackNaming,
)
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer.content_sources import (
    FPS_DEFAULT,
    RESOLUTION_PIXELS,
    AudioSourceRequest,
    VideoSourceRequest,
    resolve_audio_source,
    resolve_video_source,
)
from chaos_librarian.materializer.errors import (
    ProbeParseError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.manifest_build import augment_manifest
from chaos_librarian.materializer.phase_b.sidecar_languages import timeline_sidecar_languages
from chaos_librarian.materializer.preflight import iter_assets
from chaos_librarian.materializer.tooling.ffmpeg import build_command, run_ffmpeg
from chaos_librarian.materializer.tooling.probe import probe_file
from chaos_librarian.materializer.tooling.recipes import FFmpegInput, srt_payload
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    render_asset_path,
    render_declared_sidecar_path,
)
from chaos_librarian.topology import AssetContext, iter_asset_contexts

__all__ = [
    "MaterializeAssetResult",
    "PhaseAResult",
    "materialize_assets_phase_a",
    "materialize_one_asset",
    "stamp_phase_a_manifest",
    "write_sidecars",
]


@dataclass(frozen=True, slots=True)
class MaterializeAssetResult:
    """Phase-A result for one synthesized asset."""

    invocation: ToolInvocation
    materialized_asset: MaterializedAsset
    probed: ProbedMedia
    sidecar_hashes: dict[tuple[str, str], str]
    content_sources: tuple[ContentSourceEvidence, ...]


@dataclass(slots=True)
class PhaseAResult:
    """Accumulated Phase-A synthesis output shared across materialize modes."""

    invocations: list[ToolInvocation] = field(default_factory=list)
    materialized_assets: list[MaterializedAsset] = field(default_factory=list)
    content_sources: list[ContentSourceEvidence] = field(default_factory=list)
    probed_by_asset: dict[str, ProbedMedia] = field(default_factory=dict)
    sidecar_hashes_by_asset: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)


MaterializeAsset = Callable[..., MaterializeAssetResult]


def materialize_assets_phase_a(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    caps: Capabilities,
    result: PhaseAResult | None = None,
    stamp_manifest: bool,
    materialize_asset: MaterializeAsset | None = None,
) -> PhaseAResult:
    """Synthesize every declared asset and collect Phase-A metadata."""
    phase_a = PhaseAResult() if result is None else result
    materialize = materialize_one_asset if materialize_asset is None else materialize_asset
    primary_root_path = scenario.library.roots[0].path
    skip_by_asset = timeline_sidecar_languages(scenario)
    start_index = len(phase_a.invocations)
    for invocation_index, context in enumerate(iter_asset_contexts(scenario), start=start_index):
        asset = context.asset
        skip_languages = skip_by_asset.get(asset.id, frozenset())
        asset_result = materialize(
            asset,
            artifacts.replay_bundle.resolved_seed,
            out_dir,
            caps,
            invocation_index,
            rendered_relative_path=render_asset_path(
                _renderable_asset_context(context, primary_root_path)
            ),
            skip_languages=skip_languages,
        )
        phase_a.invocations.append(asset_result.invocation)
        phase_a.materialized_assets.append(asset_result.materialized_asset)
        phase_a.content_sources.extend(asset_result.content_sources)
        phase_a.probed_by_asset[asset.id] = asset_result.probed
        phase_a.sidecar_hashes_by_asset[asset.id] = asset_result.sidecar_hashes
        if stamp_manifest:
            augment_manifest(
                artifacts.current_manifest,
                asset,
                asset_result.materialized_asset,
                asset_result.probed,
                asset_result.sidecar_hashes,
                skip_languages=skip_languages,
            )
    return phase_a


def stamp_phase_a_manifest(
    *,
    manifest: Manifest,
    scenario: Scenario,
    phase_a: PhaseAResult,
) -> None:
    """Stamp stored Phase-A metadata onto a fresh manifest copy."""
    by_asset = {record.asset_id: record for record in phase_a.materialized_assets}
    skip_by_asset = timeline_sidecar_languages(scenario)
    for asset in iter_assets(scenario):
        materialized = by_asset.get(asset.id)
        probed = phase_a.probed_by_asset.get(asset.id)
        if materialized is None or probed is None:
            continue
        augment_manifest(
            manifest,
            asset,
            materialized,
            probed,
            phase_a.sidecar_hashes_by_asset.get(asset.id, {}),
            skip_languages=skip_by_asset.get(asset.id, frozenset()),
        )


def materialize_one_asset(
    asset: Asset,
    seed: int,
    out_dir: Path,
    caps: Capabilities,
    invocation_index: int,
    *,
    rendered_relative_path: str,
    skip_languages: frozenset[str] = frozenset(),
) -> MaterializeAssetResult:
    """Synthesize one asset, returning everything ``augment_manifest`` needs.

    ``rendered_relative_path`` is the renderer-produced media path relative
    to ``library/``. Synthesis writes the asset to
    ``<out_dir>/library/<rendered_relative_path>`` so the on-disk layout
    matches the engine and validation hierarchy renderer.

    Returning probed lets the orchestrator avoid re-probing; returning
    sidecar_hashes lets ``augment_manifest`` populate
    ``ManifestSidecar.content_hash``. Returning content-source evidence
    lets materialize/run/replay persist the Phase-A source-resolution audit.
    """
    if asset.video is None:
        raise UnsupportedMaterializationError(
            "every asset must declare a video track.",
            field="video",
            asset_id=asset.id,
            payload={},
        )
    library_dir = out_dir / "library"
    output_path = library_dir / rendered_relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = RESOLUTION_PIXELS[asset.video.resolution]
    video_resolution = resolve_video_source(
        source=asset.video.source,
        request=VideoSourceRequest(
            asset_id=asset.id,
            seed=seed,
            duration_s=asset.duration_seconds,
            width=width,
            height=height,
            fps=FPS_DEFAULT,
        ),
    )
    video_input = video_resolution.ffmpeg_input
    content_sources: list[ContentSourceEvidence] = [video_resolution.evidence]
    audio_inputs: list[FFmpegInput] = []
    for index, audio in enumerate(asset.audio):
        audio_resolution = resolve_audio_source(
            source=audio.source,
            request=AudioSourceRequest(
                asset_id=asset.id,
                track_index=index,
                seed=seed,
                duration_s=asset.duration_seconds,
                channels=audio.channels.value,
            ),
        )
        audio_inputs.append(audio_resolution.ffmpeg_input)
        content_sources.append(audio_resolution.evidence)
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
            content_sources=tuple(content_sources),
        )
    sidecar_hashes = write_sidecars(
        asset,
        library_dir,
        seed,
        rendered_relative_path=rendered_relative_path,
        skip_languages=skip_languages,
    )
    try:
        probed = probe_file(output_path)
    except ProbeParseError as exc:
        exc.content_sources = tuple(content_sources)
        raise
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
    return MaterializeAssetResult(
        invocation=invocation,
        materialized_asset=materialized_asset,
        probed=probed,
        sidecar_hashes=sidecar_hashes,
        content_sources=tuple(content_sources),
    )


def _renderable_asset_context(
    context: AssetContext,
    root_path: str,
) -> RenderableAssetContext:
    return RenderableAssetContext(
        parent_kind=context.parent_kind,
        root_path=root_path,
        layout=_layout_for_context(context),
        naming=_naming_for_context(context),
        movie_title=context.movie.title if context.movie is not None else None,
        series_title=context.series.title if context.series is not None else None,
        season_number=context.season.season_number if context.season is not None else None,
        episode_number=context.episode.episode_number if context.episode is not None else None,
        episode_title=context.episode.title if context.episode is not None else None,
        aired_on=context.episode.aired_on if context.episode is not None else None,
        absolute_number=context.episode.absolute_number if context.episode is not None else None,
        artist_name=context.artist.name if context.artist is not None else None,
        album_title=context.album.title if context.album is not None else None,
        disc_number=context.disc.disc_number if context.disc is not None else None,
        track_number=context.track.track_number if context.track is not None else None,
        track_title=context.track.title if context.track is not None else None,
        variant_label=context.variant.label,
        asset_role=context.asset.role,
        asset_container=context.asset.container,
        bundle_asset_count=context.bundle_asset_count,
    )


def _layout_for_context(context: AssetContext) -> MovieLayout | SeriesLayout | ArtistLayout:
    if context.movie is not None:
        return context.movie.layout
    if context.series is not None:
        return context.series.layout
    if context.artist is not None:
        return context.artist.layout
    raise ChaosLibrarianValueError(f"asset {context.asset.id} has no hierarchy layout")


def _naming_for_context(context: AssetContext) -> EpisodeNaming | TrackNaming | None:
    if context.series is not None:
        return context.series.episode_naming
    if context.artist is not None:
        return context.artist.track_naming
    return None


def write_sidecars(
    asset: Asset,
    library_dir: Path,
    seed: int,
    *,
    rendered_relative_path: str,
    skip_languages: frozenset[str] = frozenset(),
) -> dict[tuple[str, str], str]:
    """Write each declared SRT sidecar and return its sha256 hash.

    Preflight already rejected non-sidecar modes, so every subtitle here
    is sidecar; hash the bytes so ``augment_manifest`` can populate
    ``ManifestSidecar.content_hash``.

    ``skip_languages`` is the set of languages a timeline ``create_sidecar``
    will write in phase B; declared sidecars for those languages are
    skipped here so phase A does not leave an orphan file on disk.

    The SRT body is written directly to ``library_dir`` (not via a staging
    tempdir + ``Path.replace``). Materialize mode's recovery model is
    whole-run replay, not per-file atomicity, so a partial sidecar from an
    interrupted run is harmless — the next ``run`` rebuilds the library
    from scratch. See issue #24 for the canonical reference; if the
    recovery model ever moves to per-file atomicity, replace this with the
    ``replace_atomic_text`` helper that journal/manifest writers use.
    """
    sidecar_hashes: dict[tuple[str, str], str] = {}
    for sub in asset.subtitles:
        if sub.language in skip_languages:
            continue
        sidecar_path = library_dir / render_declared_sidecar_path(
            rendered_relative_path,
            sub.language,
        )
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        body = srt_payload(language=sub.language, duration_s=asset.duration_seconds, seed=seed)
        sidecar_path.write_text(body)
        sidecar_hashes[(asset.id, sub.language)] = (
            "sha256:" + hashlib.sha256(body.encode()).hexdigest()
        )
    return sidecar_hashes
