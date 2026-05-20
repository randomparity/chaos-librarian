"""Per-asset ffmpeg invocation, probe, and SRT sidecar emission.

These are the only filesystem-touching helpers in the materialize
pipeline (the writer flushes metadata, but ffmpeg and the sidecar writer
emit media bytes). Both functions raise ``MaterializationError``
subclasses on failure; the orchestrator in ``run.py`` converts them to
``MaterializationFailure`` records and routes them through the writer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import MaterializedAsset, ToolInvocation
from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE
from chaos_librarian.contract.scenario import Asset
from chaos_librarian.materializer.errors import ToolFailedError, UnsupportedMaterializationError
from chaos_librarian.materializer.ffmpeg import build_command, run_ffmpeg
from chaos_librarian.materializer.preflight import (
    AUDIO_RECIPES,
    FPS_DEFAULT,
    RESOLUTION_PIXELS,
    VIDEO_RECIPES,
)
from chaos_librarian.materializer.probe import probe_file
from chaos_librarian.materializer.recipes import FFmpegInput, srt_payload

__all__ = ["materialize_one_asset", "write_sidecars"]


def materialize_one_asset(
    asset: Asset,
    seed: int,
    out_dir: Path,
    caps: Capabilities,
    invocation_index: int,
    *,
    root_path: str,
) -> tuple[
    ToolInvocation,
    MaterializedAsset,
    ProbedMedia,
    dict[tuple[str, str], str],
]:
    """Synthesize one asset, returning everything ``augment_manifest`` needs.

    ``root_path`` is the primary library root's relative path (from
    ``scenario.library.roots[0].path``); synthesis writes the asset to
    ``<out_dir>/library/<root_path>/<asset_id>.<container>`` so the
    on-disk layout matches the engine-emitted ``INITIAL_PATH_TEMPLATE``
    that phase B walks.

    Returns a 4-tuple of (ffmpeg invocation, materialized asset record,
    probed-media result for the produced file, sidecar hashes keyed by
    ``(asset_id, language)``). Returning probed lets the orchestrator
    avoid re-probing; returning sidecar_hashes lets ``augment_manifest``
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
    relative_initial = INITIAL_PATH_TEMPLATE.format(
        root_path=root_path,
        asset_id=asset.id,
        container=asset.container,
    )
    output_path = library_dir / relative_initial
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = RESOLUTION_PIXELS[asset.video.resolution]
    video_recipe = VIDEO_RECIPES[asset.video.source]
    video_input = video_recipe(
        width=width,
        height=height,
        fps=FPS_DEFAULT,
        duration_s=asset.duration_seconds,
        seed=seed,
    )
    audio_inputs: list[FFmpegInput] = []
    for audio in asset.audio:
        recipe = AUDIO_RECIPES[audio.source]
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
    sidecar_hashes = write_sidecars(asset, library_dir, seed)
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


def write_sidecars(asset: Asset, library_dir: Path, seed: int) -> dict[tuple[str, str], str]:
    """Write each declared SRT sidecar and return its sha256 hash.

    Preflight already rejected non-sidecar modes, so every subtitle here
    is sidecar; hash the bytes so ``augment_manifest`` can populate
    ``ManifestSidecar.content_hash``.

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
        sidecar_path = library_dir / f"{asset.id}.{sub.language}.srt"
        body = srt_payload(language=sub.language, duration_s=asset.duration_seconds, seed=seed)
        sidecar_path.write_text(body)
        sidecar_hashes[(asset.id, sub.language)] = (
            "sha256:" + hashlib.sha256(body.encode()).hexdigest()
        )
    return sidecar_hashes
