"""Phase-A content-source resolution, synthesis, probing, and sidecar writes.

``materializer/content/*`` owns declared asset bytes before timeline effects:
deterministic content-source resolution, ffmpeg/mkvmerge synthesis, sidecar
emission, probe/hash evidence, and phase-A manifest stamping. Real timeline
filesystem and media effects live in ``materializer/phase_b/*``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.manifest import Manifest, ProbedMedia
from chaos_librarian.contract.materialization import MaterializedAsset, ToolInvocation
from chaos_librarian.contract.scenario import Asset, Scenario
from chaos_librarian.engine.plan import PlanArtifacts
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer.content.content_sources import (
    COVER_ART_SIZE,
    FPS_DEFAULT,
    RESOLUTION_PIXELS,
    AudioSourceRequest,
    ChapterSourceRequest,
    ChapterSpec,
    CoverArtSourceRequest,
    MuxingSourceRequest,
    VideoSourceRequest,
    resolve_audio_source,
    resolve_chapter_source,
    resolve_cover_art_source,
    resolve_muxing_source,
    resolve_video_source,
)
from chaos_librarian.materializer.content.manifest_build import augment_manifest
from chaos_librarian.materializer.errors import (
    ProbeParseError,
    SymlinkTargetMissingError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.preparation.preflight import iter_assets
from chaos_librarian.materializer.sidecar_planning import timeline_sidecar_languages
from chaos_librarian.materializer.tooling.ffmpeg import (
    build_command,
    build_resolution_switch_concat_command,
    build_resolution_switch_segment_command,
    run_ffmpeg,
)
from chaos_librarian.materializer.tooling.mkvmerge import (
    build_mkvmerge_command,
    run_mkvmerge,
)
from chaos_librarian.materializer.tooling.probe import probe_file
from chaos_librarian.materializer.tooling.recipes import FFmpegInput
from chaos_librarian.materializer.tooling.subtitles import subtitle_payload_bytes
from chaos_librarian.media_matrix import (
    RESOLUTION_SWITCH_VIDEO_CODEC,
    RESOLUTION_SWITCH_VIDEO_CONTAINER,
    RESOLUTION_SWITCH_VIDEO_RESOLUTION,
    RESOLUTION_SWITCH_VIDEO_SOURCE,
)
from chaos_librarian.path_rendering import render_asset_path, render_declared_sidecar_path
from chaos_librarian.topology import iter_asset_contexts, renderable_asset_context

__all__ = [
    "MaterializeAssetResult",
    "PhaseAInputs",
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
    prelude_invocations: tuple[ToolInvocation, ...] = ()


@dataclass(slots=True)
class PhaseAResult:
    """Accumulated Phase-A synthesis output shared across materialize modes."""

    invocations: list[ToolInvocation] = field(default_factory=list)
    materialized_assets: list[MaterializedAsset] = field(default_factory=list)
    content_sources: list[ContentSourceEvidence] = field(default_factory=list)
    probed_by_asset: dict[str, ProbedMedia] = field(default_factory=dict)
    sidecar_hashes_by_asset: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)


MaterializeAsset = Callable[..., MaterializeAssetResult]


@dataclass(slots=True)
class PhaseAInputs:
    """Run facts required to synthesize declared assets in phase A."""

    scenario: Scenario
    out_dir: Path
    artifacts: PlanArtifacts
    caps: Capabilities
    stamp_manifest: bool
    phase_a_accumulator: PhaseAResult | None = None
    materialize_asset: MaterializeAsset | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedMediaInputs:
    video_input: FFmpegInput | None
    audio_inputs: tuple[FFmpegInput, ...]
    content_sources: tuple[ContentSourceEvidence, ...]


@dataclass(frozen=True, slots=True)
class _EmbeddedMetadataInputs:
    chapters_input: FFmpegInput | None
    cover_art_input: FFmpegInput | None
    content_sources: tuple[ContentSourceEvidence, ...]
    prelude_invocations: tuple[ToolInvocation, ...]


@dataclass(frozen=True, slots=True)
class _MediaInvocationResult:
    invocation: ToolInvocation
    content_sources: tuple[ContentSourceEvidence, ...]
    prelude_invocations: tuple[ToolInvocation, ...]


def materialize_assets_phase_a(inputs: PhaseAInputs) -> PhaseAResult:
    """Synthesize every declared asset and collect Phase-A metadata."""
    phase_a = PhaseAResult() if inputs.phase_a_accumulator is None else inputs.phase_a_accumulator
    materialize = (
        materialize_one_asset if inputs.materialize_asset is None else inputs.materialize_asset
    )
    primary_root_path = inputs.scenario.library.roots[0].path
    skip_by_asset = timeline_sidecar_languages(inputs.scenario)
    rel_path_by_asset: dict[str, str] = {}
    for context in iter_asset_contexts(inputs.scenario):
        asset = context.asset
        skip_languages = skip_by_asset.get(asset.id, frozenset())
        invocation_index = len(phase_a.invocations)
        rendered_relative_path = render_asset_path(
            renderable_asset_context(context, primary_root_path)
        )
        rel_path_by_asset[asset.id] = rendered_relative_path
        if asset.symlink is not None:
            referent_rel_path = (
                rel_path_by_asset[asset.symlink.to_asset]
                if asset.symlink.to_asset is not None
                else None
            )
            asset_result = _symlink_asset(
                asset=asset,
                out_dir=inputs.out_dir,
                rendered_relative_path=rendered_relative_path,
                referent_rel_path=referent_rel_path,
                invocation_index=invocation_index,
            )
        elif asset.hardlinked_to is not None:
            asset_result = _hardlink_asset(
                asset=asset,
                out_dir=inputs.out_dir,
                rendered_relative_path=rendered_relative_path,
                referent_rel_path=rel_path_by_asset[asset.hardlinked_to],
                invocation_index=invocation_index,
            )
        elif asset.same_content_as is not None:
            asset_result = _copy_same_content_asset(
                asset=asset,
                out_dir=inputs.out_dir,
                rendered_relative_path=rendered_relative_path,
                referent_rel_path=rel_path_by_asset[asset.same_content_as],
                invocation_index=invocation_index,
            )
        else:
            asset_result = materialize(
                asset,
                inputs.artifacts.replay_bundle.resolved_seed,
                inputs.out_dir,
                inputs.caps,
                invocation_index,
                rendered_relative_path=rendered_relative_path,
                skip_languages=skip_languages,
            )
        phase_a.invocations.extend(asset_result.prelude_invocations)
        materialized_asset = asset_result.materialized_asset.model_copy(
            update={"invocation_index": len(phase_a.invocations)}
        )
        phase_a.invocations.append(asset_result.invocation)
        phase_a.materialized_assets.append(materialized_asset)
        phase_a.content_sources.extend(asset_result.content_sources)
        phase_a.probed_by_asset[asset.id] = asset_result.probed
        phase_a.sidecar_hashes_by_asset[asset.id] = asset_result.sidecar_hashes
        if inputs.stamp_manifest:
            augment_manifest(
                inputs.artifacts.current_manifest,
                asset,
                asset_result.materialized_asset,
                asset_result.probed,
                asset_result.sidecar_hashes,
                skip_languages=skip_languages,
            )
    return phase_a


def _copy_same_content_asset(
    *,
    asset: Asset,
    out_dir: Path,
    rendered_relative_path: str,
    referent_rel_path: str,
    invocation_index: int,
) -> MaterializeAssetResult:
    """Copy a referent asset's already-written bytes for a ``same_content_as`` asset.

    Reproduces every per-asset contribution synthesis makes so the phase-A
    invariants hold: a synthetic ``same_content_copy`` ``ToolInvocation`` (keeping
    "one invocation per asset" and giving the duplicate a real
    ``invocation_index``), a re-probe of the copied file (not a reuse of the
    referent's probe), empty ``sidecar_hashes`` (``same_content_as`` forbids the
    asset's own subtitles), and no ``content_sources`` (a copy resolves no
    synthesis source). The referent materialized earlier in the same
    declaration-ordered pass, so its file already exists on disk.
    """
    library_dir = out_dir / "library"
    referent_path = library_dir / referent_rel_path
    output_path = library_dir / rendered_relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    shutil.copyfile(referent_path, output_path)
    duration_ns = time.monotonic_ns() - started
    with output_path.open("rb") as fh:
        content_hash = "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
    probed = probe_file(output_path)
    invocation = ToolInvocation(
        tool="same_content_copy",
        version="n/a",
        command=["copyfile", asset.same_content_as or "", str(output_path.relative_to(out_dir))],
        exit_code=0,
        duration_ns=duration_ns,
    )
    materialized_asset = MaterializedAsset(
        asset_id=asset.id,
        location_path=str(output_path.relative_to(out_dir)),
        content_hash=content_hash,
        size_bytes=probed.size_bytes,
        duration_seconds=probed.duration_seconds,
        invocation_index=invocation_index,
        mp4_moov_placement=asset.mp4_moov_placement,
    )
    return MaterializeAssetResult(
        invocation=invocation,
        materialized_asset=materialized_asset,
        probed=probed,
        sidecar_hashes={},
        content_sources=(),
        prelude_invocations=(),
    )


def _hardlink_asset(
    *,
    asset: Asset,
    out_dir: Path,
    rendered_relative_path: str,
    referent_rel_path: str,
    invocation_index: int,
) -> MaterializeAssetResult:
    """Hardlink a referent asset's already-written file for a ``hardlinked_to`` asset.

    A near-twin of ``_copy_same_content_asset`` that swaps ``shutil.copyfile`` for
    ``os.link``: instead of an independent byte copy, the referrer's path becomes a
    second directory entry for the **same inode** (shared ``st_ino``/``st_dev``,
    link count >= 2). The shared inode is observed on disk by the consumer; the
    manifest records nothing inode-specific (the same full ``content_hash`` is
    stamped on both, since the bytes are literally identical). Reproduces every
    per-asset contribution synthesis makes so the phase-A invariants hold: a
    synthetic ``hardlink`` ``ToolInvocation``, a re-probe of the linked file, empty
    ``sidecar_hashes`` (``hardlinked_to`` forbids the asset's own subtitles), and no
    ``content_sources`` (a link resolves no synthesis source). ``os.link`` is
    non-overwriting; the referent materialized earlier in the same
    declaration-ordered pass and phase A writes into a freshly-created library tree,
    so ``output_path`` never pre-exists.
    """
    library_dir = out_dir / "library"
    referent_path = library_dir / referent_rel_path
    output_path = library_dir / rendered_relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic_ns()
    os.link(referent_path, output_path)
    duration_ns = time.monotonic_ns() - started
    with output_path.open("rb") as fh:
        content_hash = "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
    probed = probe_file(output_path)
    invocation = ToolInvocation(
        tool="hardlink",
        version="n/a",
        command=["link", asset.hardlinked_to or "", str(output_path.relative_to(out_dir))],
        exit_code=0,
        duration_ns=duration_ns,
    )
    materialized_asset = MaterializedAsset(
        asset_id=asset.id,
        location_path=str(output_path.relative_to(out_dir)),
        content_hash=content_hash,
        size_bytes=probed.size_bytes,
        duration_seconds=probed.duration_seconds,
        invocation_index=invocation_index,
        mp4_moov_placement=asset.mp4_moov_placement,
    )
    return MaterializeAssetResult(
        invocation=invocation,
        materialized_asset=materialized_asset,
        probed=probed,
        sidecar_hashes={},
        content_sources=(),
        prelude_invocations=(),
    )


def _symlink_asset(
    *,
    asset: Asset,
    out_dir: Path,
    rendered_relative_path: str,
    referent_rel_path: str | None,
    invocation_index: int,
) -> MaterializeAssetResult:
    """Materialize a ``symlink`` asset's path as an ``os.symlink``.

    A sibling of ``_hardlink_asset`` that swaps ``os.link`` for ``os.symlink``:
    the referrer's path becomes a symbolic link, not a regular file or a shared
    inode. The link target is either an in-root asset's already-written file
    (``to_asset`` ⇒ ``referent_rel_path``) or a library-escaping run-dir path
    (``to_run_dir_path``); the escaping target is sandboxed to the run dir by
    ``rule_symlink_target_escape`` at validate time. v1 requires the resolved
    target to exist on disk (dangling links are deferred); a missing target
    raises ``SymlinkTargetMissingError`` rather than creating a dangling link.

    The link is created with a **run-dir-relative** target
    (``os.path.relpath`` against the link's own parent) so the materialized tree
    is portable and replay-stable — no absolute run-specific path is written to
    disk. The referrer's ``content_hash`` and probe come from the resolved
    target (``open``/``probe_file`` follow the link). Reproduces every per-asset
    contribution synthesis makes so the phase-A invariants hold: a synthetic
    ``symlink`` ``ToolInvocation``, empty ``sidecar_hashes`` (``symlink`` forbids
    the asset's own subtitles), and no ``content_sources`` (a link resolves no
    synthesis source). ``os.symlink`` is non-overwriting and phase A writes into
    a freshly-created library tree, so ``output_path`` never pre-exists.
    """
    symlink = asset.symlink
    if symlink is None:  # pragma: no cover - dispatch guarantees this
        raise ChaosLibrarianValueError("_symlink_asset called for an asset without symlink")
    library_dir = out_dir / "library"
    output_path = library_dir / rendered_relative_path
    if referent_rel_path is not None:
        target_path = library_dir / referent_rel_path
        target_descriptor = symlink.to_asset or ""
    else:
        target_path = out_dir / (symlink.to_run_dir_path or "")
        target_descriptor = symlink.to_run_dir_path or ""
    if not target_path.exists():
        raise SymlinkTargetMissingError(
            f"symlink target for asset {asset.id!r} does not exist: {target_descriptor!r}",
            asset_id=asset.id,
            field="symlink",
            payload={"target": target_descriptor},
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    relative_target = os.path.relpath(target_path, output_path.parent)
    started = time.monotonic_ns()
    os.symlink(relative_target, output_path)
    duration_ns = time.monotonic_ns() - started
    with output_path.open("rb") as fh:
        content_hash = "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
    probed = probe_file(output_path)
    invocation = ToolInvocation(
        tool="symlink",
        version="n/a",
        command=["symlink", target_descriptor, str(output_path.relative_to(out_dir))],
        exit_code=0,
        duration_ns=duration_ns,
    )
    materialized_asset = MaterializedAsset(
        asset_id=asset.id,
        location_path=str(output_path.relative_to(out_dir)),
        content_hash=content_hash,
        size_bytes=probed.size_bytes,
        duration_seconds=probed.duration_seconds,
        invocation_index=invocation_index,
        mp4_moov_placement=asset.mp4_moov_placement,
    )
    return MaterializeAssetResult(
        invocation=invocation,
        materialized_asset=materialized_asset,
        probed=probed,
        sidecar_hashes={},
        content_sources=(),
        prelude_invocations=(),
    )


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
    library_dir = out_dir / "library"
    output_path = library_dir / rendered_relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if asset.video is not None and asset.video.resolution_sequence is not None:
        return _materialize_resolution_switch_asset(
            asset=asset,
            seed=seed,
            output_path=output_path,
            out_dir=out_dir,
            caps=caps,
            invocation_index=invocation_index,
        )
    resolved_inputs = _resolve_media_inputs(asset, seed)
    with TemporaryDirectory(prefix=f".{output_path.stem}-", dir=output_path.parent) as temp_dir:
        embedded_inputs = _prepare_embedded_metadata_inputs(
            asset=asset,
            seed=seed,
            caps=caps,
            temp_path=Path(temp_dir),
            base_content_sources=resolved_inputs.content_sources,
        )
        media_result = _run_media_invocation(
            asset=asset,
            seed=seed,
            output_path=output_path,
            caps=caps,
            temp_path=Path(temp_dir),
            resolved_inputs=resolved_inputs,
            embedded_inputs=embedded_inputs,
        )
    invocation = media_result.invocation
    content_sources = media_result.content_sources
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
        exc.content_sources = content_sources
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
        mp4_moov_placement=asset.mp4_moov_placement,
    )
    return MaterializeAssetResult(
        invocation=invocation,
        materialized_asset=materialized_asset,
        probed=probed,
        sidecar_hashes=sidecar_hashes,
        content_sources=content_sources,
        prelude_invocations=media_result.prelude_invocations,
    )


def _run_media_invocation(
    *,
    asset: Asset,
    seed: int,
    output_path: Path,
    caps: Capabilities,
    temp_path: Path,
    resolved_inputs: _ResolvedMediaInputs,
    embedded_inputs: _EmbeddedMetadataInputs,
) -> _MediaInvocationResult:
    content_sources = resolved_inputs.content_sources + embedded_inputs.content_sources
    profile = asset.matroska_muxing_profile
    ffmpeg_output_path = output_path if profile is None else temp_path / f"media.{asset.container}"
    argv = build_command(
        video=asset.video,
        video_input=resolved_inputs.video_input,
        audios=asset.audio,
        audio_inputs=resolved_inputs.audio_inputs,
        output_path=ffmpeg_output_path,
        mp4_moov_placement=asset.mp4_moov_placement,
        chapters_input=embedded_inputs.chapters_input,
        cover_art_input=embedded_inputs.cover_art_input,
    )
    invocation, stderr_tail = run_ffmpeg(
        argv,
        ffmpeg_version=caps.ffmpeg.version or "unknown",
    )
    if invocation.exit_code != 0:
        raise _tool_failed(
            asset=asset,
            invocation=invocation,
            stderr_tail=stderr_tail,
            content_sources=content_sources,
        )
    if profile is None:
        return _MediaInvocationResult(
            invocation=invocation,
            content_sources=content_sources,
            prelude_invocations=embedded_inputs.prelude_invocations,
        )
    return _run_mkvmerge_finalization(
        asset=asset,
        seed=seed,
        output_path=output_path,
        input_path=ffmpeg_output_path,
        caps=caps,
        ffmpeg_invocation=invocation,
        prelude_invocations=embedded_inputs.prelude_invocations,
        content_sources=content_sources,
    )


def _run_mkvmerge_finalization(
    *,
    asset: Asset,
    seed: int,
    output_path: Path,
    input_path: Path,
    caps: Capabilities,
    ffmpeg_invocation: ToolInvocation,
    prelude_invocations: tuple[ToolInvocation, ...],
    content_sources: tuple[ContentSourceEvidence, ...],
) -> _MediaInvocationResult:
    profile = asset.matroska_muxing_profile
    if profile is None:
        raise ChaosLibrarianValueError("mkvmerge finalization requires a muxing profile")
    muxing_resolution = resolve_muxing_source(
        MuxingSourceRequest(
            asset_id=asset.id,
            seed=seed,
            container=asset.container,
            profile=profile,
        )
    )
    content_sources = (*content_sources, muxing_resolution.evidence)
    argv = build_mkvmerge_command(
        input_path=input_path,
        output_path=output_path,
        container=asset.container,
        profile=profile,
        deterministic_seed=muxing_resolution.deterministic_seed,
    )
    invocation, stderr_tail = run_mkvmerge(
        argv,
        mkvmerge_version=caps.mkvtoolnix.version or "unknown",
    )
    if invocation.exit_code != 0:
        raise _tool_failed(
            asset=asset,
            invocation=invocation,
            stderr_tail=stderr_tail,
            content_sources=content_sources,
        )
    return _MediaInvocationResult(
        invocation=invocation,
        content_sources=content_sources,
        prelude_invocations=(*prelude_invocations, ffmpeg_invocation),
    )


def _prepare_embedded_metadata_inputs(
    *,
    asset: Asset,
    seed: int,
    caps: Capabilities,
    temp_path: Path,
    base_content_sources: tuple[ContentSourceEvidence, ...],
) -> _EmbeddedMetadataInputs:
    content_sources: list[ContentSourceEvidence] = []
    prelude_invocations: list[ToolInvocation] = []
    chapters_input = None
    cover_art_input = None
    if asset.embedded_chapters is not None:
        chapter_resolution = resolve_chapter_source(
            ChapterSourceRequest(
                asset_id=asset.id,
                seed=seed,
                duration_s=asset.duration_seconds,
                chapters=asset.embedded_chapters,
            )
        )
        chapter_path = temp_path / "chapters.ffmeta"
        _write_chapter_metadata(chapter_path, chapter_resolution.chapters)
        chapters_input = FFmpegInput(
            file_path=chapter_path,
            extra_flags=("-f", "ffmetadata"),
        )
        content_sources.append(chapter_resolution.evidence)
    if asset.embedded_cover_art is not None:
        cover_resolution = resolve_cover_art_source(
            CoverArtSourceRequest(
                asset_id=asset.id,
                seed=seed,
                cover_art=asset.embedded_cover_art,
            )
        )
        cover_path = temp_path / f"cover.{asset.embedded_cover_art.image_format.value}"
        invocation = _run_cover_art_prelude(
            asset=asset,
            caps=caps,
            color=cover_resolution.color,
            output_path=cover_path,
            content_sources=(*base_content_sources, *content_sources, cover_resolution.evidence),
        )
        cover_art_input = FFmpegInput(file_path=cover_path)
        content_sources.append(cover_resolution.evidence)
        prelude_invocations.append(invocation)
    return _EmbeddedMetadataInputs(
        chapters_input=chapters_input,
        cover_art_input=cover_art_input,
        content_sources=tuple(content_sources),
        prelude_invocations=tuple(prelude_invocations),
    )


def _write_chapter_metadata(path: Path, chapters: tuple[ChapterSpec, ...]) -> None:
    lines = [";FFMETADATA1\n"]
    for chapter in chapters:
        escaped_title = chapter.title.replace("\\", "\\\\").replace("\n", " ")
        lines.extend(
            [
                "[CHAPTER]\n",
                "TIMEBASE=1/1000\n",
                f"START={chapter.start_ms}\n",
                f"END={chapter.end_ms}\n",
                f"title={escaped_title}\n",
            ]
        )
    path.write_text("".join(lines), encoding="utf-8")


def _run_cover_art_prelude(
    *,
    asset: Asset,
    caps: Capabilities,
    color: str,
    output_path: Path,
    content_sources: tuple[ContentSourceEvidence, ...],
) -> ToolInvocation:
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={COVER_ART_SIZE}",
        "-frames:v",
        "1",
        str(output_path),
    ]
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=caps.ffmpeg.version or "unknown")
    if invocation.exit_code != 0:
        raise _tool_failed(
            asset=asset,
            invocation=invocation,
            stderr_tail=stderr_tail,
            content_sources=content_sources,
        )
    return invocation


def _materialize_resolution_switch_asset(
    *,
    asset: Asset,
    seed: int,
    output_path: Path,
    out_dir: Path,
    caps: Capabilities,
    invocation_index: int,
) -> MaterializeAssetResult:
    video = asset.video
    if video is None or video.resolution_sequence is None:
        raise UnsupportedMaterializationError(
            "resolution-switch asset requires a video resolution_sequence",
            field="video.resolution_sequence",
            asset_id=asset.id,
            payload={},
        )
    _validate_resolution_switch_asset(asset)
    content_sources, segment_inputs = _resolve_resolution_switch_inputs(asset, seed)
    with TemporaryDirectory(prefix=f".{output_path.stem}-", dir=output_path.parent) as temp_dir:
        temp_path = Path(temp_dir)
        segment_paths = (temp_path / "segment-sd.ts", temp_path / "segment-hd.ts")
        prelude_invocations = _run_resolution_switch_segments(
            asset=asset,
            caps=caps,
            content_sources=content_sources,
            segment_inputs=segment_inputs,
            segment_paths=segment_paths,
        )
        concat_list = temp_path / "concat.txt"
        _write_concat_list(concat_list, segment_paths)
        argv = build_resolution_switch_concat_command(
            concat_list_path=concat_list,
            output_path=output_path,
        )
        invocation, stderr_tail = run_ffmpeg(
            argv,
            ffmpeg_version=caps.ffmpeg.version or "unknown",
        )
        if invocation.exit_code != 0:
            raise _tool_failed(
                asset=asset,
                invocation=invocation,
                stderr_tail=stderr_tail,
                content_sources=content_sources,
            )
    try:
        probed = probe_file(output_path)
    except ProbeParseError as exc:
        exc.content_sources = content_sources
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
        sidecar_hashes={},
        content_sources=content_sources,
        prelude_invocations=prelude_invocations,
    )


def _resolve_resolution_switch_inputs(
    asset: Asset,
    seed: int,
) -> tuple[tuple[ContentSourceEvidence, ...], tuple[FFmpegInput, FFmpegInput]]:
    video = asset.video
    if video is None or video.resolution_sequence is None:
        raise UnsupportedMaterializationError(
            "resolution-switch asset requires a video resolution_sequence",
            field="video.resolution_sequence",
            asset_id=asset.id,
            payload={},
        )
    segment_duration = asset.duration_seconds / 2
    sd_width, sd_height = RESOLUTION_PIXELS["sd"]
    hd_width, hd_height = RESOLUTION_PIXELS["hd"]
    sd_resolution = resolve_video_source(
        source=video.source,
        request=VideoSourceRequest(
            asset_id=asset.id,
            seed=seed,
            duration_s=segment_duration,
            width=sd_width,
            height=sd_height,
            fps=FPS_DEFAULT,
            resolution_sequence=video.resolution_sequence,
        ),
    )
    hd_resolution = resolve_video_source(
        source=video.source,
        request=VideoSourceRequest(
            asset_id=asset.id,
            seed=seed,
            duration_s=segment_duration,
            width=hd_width,
            height=hd_height,
            fps=FPS_DEFAULT,
            resolution_sequence=video.resolution_sequence,
        ),
    )
    return (
        (sd_resolution.evidence, hd_resolution.evidence),
        (sd_resolution.ffmpeg_input, hd_resolution.ffmpeg_input),
    )


def _run_resolution_switch_segments(
    *,
    asset: Asset,
    caps: Capabilities,
    content_sources: tuple[ContentSourceEvidence, ...],
    segment_inputs: tuple[FFmpegInput, FFmpegInput],
    segment_paths: tuple[Path, Path],
) -> tuple[ToolInvocation, ...]:
    invocations: list[ToolInvocation] = []
    for video_input, segment_path in zip(segment_inputs, segment_paths, strict=True):
        argv = build_resolution_switch_segment_command(
            video_input=video_input,
            output_path=segment_path,
        )
        invocation, stderr_tail = run_ffmpeg(
            argv,
            ffmpeg_version=caps.ffmpeg.version or "unknown",
        )
        if invocation.exit_code != 0:
            raise _tool_failed(
                asset=asset,
                invocation=invocation,
                stderr_tail=stderr_tail,
                content_sources=content_sources,
            )
        invocations.append(invocation)
    return tuple(invocations)


def _write_concat_list(concat_list: Path, segment_paths: tuple[Path, Path]) -> None:
    lines = [f"file '{_escape_concat_path(path)}'\n" for path in segment_paths]
    concat_list.write_text("".join(lines), encoding="utf-8")


def _escape_concat_path(path: Path) -> str:
    return str(path).replace("'", "'\\''")


def _tool_failed(
    *,
    asset: Asset,
    invocation: ToolInvocation,
    stderr_tail: str,
    content_sources: tuple[ContentSourceEvidence, ...],
) -> ToolFailedError:
    return ToolFailedError(
        f"{invocation.tool} exit {invocation.exit_code} for asset {asset.id}",
        asset_id=asset.id,
        field=None,
        payload={
            "stderr_tail": stderr_tail,
            "exit_code": invocation.exit_code,
        },
        invocation=invocation,
        content_sources=content_sources,
    )


def _validate_resolution_switch_asset(asset: Asset) -> None:
    video = asset.video
    if video is None:
        raise UnsupportedMaterializationError(
            "resolution-switch asset requires a video track",
            field="video",
            asset_id=asset.id,
            payload={},
        )
    for value, expected, field_name in (
        (asset.container, RESOLUTION_SWITCH_VIDEO_CONTAINER, "container"),
        (video.source.value, RESOLUTION_SWITCH_VIDEO_SOURCE, "video.source"),
        (video.codec, RESOLUTION_SWITCH_VIDEO_CODEC, "video.codec"),
        (video.resolution, RESOLUTION_SWITCH_VIDEO_RESOLUTION, "video.resolution"),
    ):
        if value == expected:
            continue
        raise UnsupportedMaterializationError(
            f"resolution-switch video materialization requires {field_name}={expected!r}",
            field=field_name,
            asset_id=asset.id,
            payload={"expected": expected, "actual": value},
        )
    if asset.audio:
        raise UnsupportedMaterializationError(
            "resolution-switch video materialization does not support audio streams",
            field="audio",
            asset_id=asset.id,
            payload={"count": len(asset.audio)},
        )
    if asset.subtitles:
        raise UnsupportedMaterializationError(
            "resolution-switch video materialization does not support subtitles",
            field="subtitles",
            asset_id=asset.id,
            payload={"count": len(asset.subtitles)},
        )
    if asset.embedded_chapters is not None:
        raise UnsupportedMaterializationError(
            "resolution-switch video materialization cannot embed chapters",
            field="embedded_chapters",
            asset_id=asset.id,
            payload={},
        )
    if asset.embedded_cover_art is not None:
        raise UnsupportedMaterializationError(
            "resolution-switch video materialization cannot embed cover art",
            field="embedded_cover_art",
            asset_id=asset.id,
            payload={},
        )
    for field_name, value in (
        ("vfr_cadence", video.vfr_cadence),
        ("field_order", video.field_order),
        ("color_space", video.color_space),
        ("color_range", video.color_range),
        ("hdr_mode", video.hdr_mode),
    ):
        if value is None:
            continue
        raise UnsupportedMaterializationError(
            f"resolution-switch video materialization cannot combine {field_name}",
            field=f"video.{field_name}",
            asset_id=asset.id,
            payload={field_name: value.value},
        )


def _resolve_media_inputs(asset: Asset, seed: int) -> _ResolvedMediaInputs:
    """Resolve source recipes into FFmpeg inputs and content-source evidence."""
    video_input = None
    content_sources: list[ContentSourceEvidence] = []
    video = asset.video
    if video is not None:
        width, height = RESOLUTION_PIXELS[video.resolution]
        video_resolution = resolve_video_source(
            source=video.source,
            request=VideoSourceRequest(
                asset_id=asset.id,
                seed=seed,
                duration_s=asset.duration_seconds,
                width=width,
                height=height,
                fps=FPS_DEFAULT,
                vfr_cadence=video.vfr_cadence,
                field_order=video.field_order,
                color_space=video.color_space,
                color_range=video.color_range,
                hdr_mode=video.hdr_mode,
                resolution_sequence=video.resolution_sequence,
            ),
        )
        video_input = video_resolution.ffmpeg_input
        content_sources.append(video_resolution.evidence)
    elif asset.subtitles:
        raise UnsupportedMaterializationError(
            "audio-only assets must not declare subtitles.",
            field="subtitles",
            asset_id=asset.id,
            payload={},
        )

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
                noise_color=audio.noise_color,
                sample_rate=audio.sample_rate,
                sample_format=audio.sample_format,
            ),
        )
        audio_inputs.append(audio_resolution.ffmpeg_input)
        content_sources.append(audio_resolution.evidence)

    return _ResolvedMediaInputs(
        video_input=video_input,
        audio_inputs=tuple(audio_inputs),
        content_sources=tuple(content_sources),
    )


def write_sidecars(
    asset: Asset,
    library_dir: Path,
    seed: int,
    *,
    rendered_relative_path: str,
    skip_languages: frozenset[str] = frozenset(),
) -> dict[tuple[str, str], str]:
    """Write each declared subtitle sidecar and return its sha256 hash.

    Preflight already rejected non-sidecar modes, so every subtitle here
    is sidecar; hash the bytes so ``augment_manifest`` can populate
    ``ManifestSidecar.content_hash``.

    ``skip_languages`` is the set of languages a timeline ``create_sidecar``
    will write in phase B; declared sidecars for those languages are
    skipped here so phase A does not leave an orphan file on disk.

    The sidecar body is written directly to ``library_dir`` (not via a staging
    tempdir + ``Path.replace``). Materialize mode's recovery model is
    whole-run replay, not per-file atomicity, so a partial sidecar from an
    interrupted run is harmless — the next ``run`` rebuilds the library
    from scratch. See issue #24 for the canonical reference; if the
    recovery model ever moves to per-file atomicity, replace this with the
    byte-oriented atomic replacement helper.
    """
    sidecar_hashes: dict[tuple[str, str], str] = {}
    for sub in asset.subtitles:
        if sub.language in skip_languages:
            continue
        sidecar_path = library_dir / render_declared_sidecar_path(
            rendered_relative_path,
            sub.language,
            codec=sub.codec.value,
        )
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        body = subtitle_payload_bytes(
            codec=sub.codec,
            source=sub.source,
            encoding=sub.encoding,
            timing_profile=sub.timing_profile,
            language=sub.language,
            duration_s=asset.duration_seconds,
            seed=seed,
        )
        sidecar_path.write_bytes(body)
        sidecar_hashes[(asset.id, sub.language)] = "sha256:" + hashlib.sha256(body).hexdigest()
    return sidecar_hashes
