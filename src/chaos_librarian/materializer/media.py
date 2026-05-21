"""Phase-B media dispatcher — ffmpeg-backed handlers for byte-changing events.

Parallel to Sprint 6's ``materializer/filesystem.py``: one handler per
media action, each reads every path from the journal entry's
``state_delta`` and writes through an atomic-rename temp-file.

The orchestrator in ``materializer/run.py`` walks the journal once and
dispatches each entry to ``apply_media_action`` here OR to the stdlib
dispatcher in ``filesystem.py``. See ``_MEDIA_ACTIONS`` /
``_STDLIB_ACTIONS`` below.

Per-action ffmpeg sketches are in the Sprint 7 spec
§"Per-action behavior" table.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import MediaAction, ToolInvocation
from chaos_librarian.contract.scenario import Asset, SidecarKind, TimelineActionName
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.ffmpeg import BITEXACT_FLAGS, run_ffmpeg
from chaos_librarian.materializer.preflight import SUPPORTED_S6_ACTIONS
from chaos_librarian.materializer.probe import probe_file
from chaos_librarian.materializer.sidecar_bytes import regenerate_sidecar

if TYPE_CHECKING:
    from chaos_librarian.contract.manifest import ManifestSidecar

__all__ = [
    "SUPPORTED_S7_ACTIONS",
    "_MEDIA_ACTIONS",
    "_STDLIB_ACTIONS",
    "_MediaContext",
    "_subtitle_codec_for_container",
    "apply_media_action",
]


_SUBTITLE_CODEC_BY_CONTAINER: Final[dict[str, str]] = {
    "mkv": "srt",
    "webm": "srt",
    "mp4": "mov_text",
    "m4v": "mov_text",
    "mov": "mov_text",
}


# ffmpeg's ``-ac`` flag requires an integer channel count, but the
# scenario contract's ``AudioTrack.channels`` is a free-form ``str`` so
# authors can write the natural ``"stereo"`` / ``"5.1"`` shorthand.
# Translate names to integers before invoking ffmpeg (#58).
_CHANNEL_COUNT_BY_NAME: Final[dict[str, int]] = {
    "mono": 1,
    "stereo": 2,
    "2.1": 3,
    "5.1": 6,
    "7.1": 8,
}


def _channel_count_for(name: str) -> int:
    """Return the integer channel count for a scenario channel name.

    Raises ValueError when ``name`` isn't a known channel layout; the
    caller wraps that in a MediaActionError so the user sees
    E_MATERIALIZE_MEDIA_FAILED before ffmpeg is invoked.
    """
    count = _CHANNEL_COUNT_BY_NAME.get(name.lower())
    if count is None:
        raise ValueError(
            f"unknown audio channel layout {name!r}; supported: {sorted(_CHANNEL_COUNT_BY_NAME)}"
        )
    return count


def _subtitle_codec_for_container(container_ext: str) -> str:
    """Return the ffmpeg ``-c:s`` argument for a given container extension.

    MKV / WebM → ``srt``. MP4 / M4V / MOV → ``mov_text``. Other
    containers raise ValueError; the per-action handler wraps that in
    a MediaActionError so the user sees E_MATERIALIZE_MEDIA_FAILED.
    """
    codec = _SUBTITLE_CODEC_BY_CONTAINER.get(container_ext.lower())
    if codec is None:
        raise ValueError(
            f"unsupported container {container_ext!r} for subtitle codec selection; "
            f"supported: {sorted(_SUBTITLE_CODEC_BY_CONTAINER)}"
        )
    return codec


@dataclass(slots=True)
class _MediaContext:
    """Per-run state threaded through every media handler.

    Mirrors ``filesystem._PhaseBContext`` but carries extra fields the
    media dispatcher needs (ffmpeg/ffprobe version strings, post-phase-B
    version + sidecar hash dicts that ``manifest_build.augment_versions``
    / ``augment_updated_sidecars`` will drain).
    """

    library_root: Path
    scenario_assets: Mapping[str, Asset]
    resolved_seed: int
    ffmpeg_version: str
    ffprobe_version: str
    # Filled by handlers; drained by manifest_build.augment_versions.
    post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]] = field(default_factory=dict)
    # Filled by handlers; drained by manifest_build.augment_updated_sidecars.
    # Maps sidecar_id -> (content_hash, output_path).
    post_phase_b_sidecars: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Shared with the orchestrator so each media handler's ffmpeg/ffprobe
    # calls append to the same MaterializationReport.invocations list.
    invocations: list[ToolInvocation] = field(default_factory=list)
    # update_sidecar needs the (kind, language) recorded on the existing
    # ManifestSidecar; the orchestrator passes a lookup callable so this
    # module doesn't import from manifest_build.
    sidecar_lookup: Callable[[str], ManifestSidecar | None] | None = None


_RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}


def _temp_sibling(output_path: Path, resolved_seed: int) -> Path:
    """Return ``<stem>.tmp.<resolved_seed><suffix>`` sibling Path.

    The suffix order matters: ffmpeg infers its muxer from the trailing
    extension, so a ``.tmp.<seed>`` tail would defeat format detection
    (#56). Keeping the original suffix at the end preserves ffmpeg's
    auto-detection while still landing the temp file in the same
    directory for ``Path.replace`` to atomically rename over the final
    name. Files with no suffix get ``.tmp.<seed>`` appended unchanged.
    """
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.tmp.{resolved_seed}{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.tmp.{resolved_seed}")


def _hash_file(path: Path) -> str:
    """Return ``sha256:<hex>`` for the file at ``path``."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _apply_reencode_video(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """Re-encode video in place; produce a new ManifestVersion's content_hash.

    Writes ffmpeg's output to a ``<output>.tmp.<resolved_seed>`` sibling
    then atomically renames it over the final path so a crashed run
    never leaves a half-written file. Re-hashes and re-probes the
    output, stashing both on ``ctx.post_phase_b_versions`` for
    ``manifest_build.augment_versions`` to drain.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    resolution = str(delta["resolution"])
    width, height = _RESOLUTION_PIXELS.get(resolution, (640, 480))
    codec = str(delta["codec"])
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        f"scale={width}:{height}",
        "-c:v",
        codec,
        "-c:a",
        "copy",
        "-c:s",
        "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"reencode_video failed for event {entry.event_id}: ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_VIDEO,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path)
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_VIDEO,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_reencode_audio(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """Re-encode audio in place. from_channels is descriptive; -ac uses to_channels."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    to_channels_name = str(delta["to_channels"])
    try:
        ac_value = _channel_count_for(to_channels_name)
    except ValueError as exc:
        raise MediaActionError(
            f"reencode_audio: unknown to_channels {to_channels_name!r} for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=exc,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-c:v",
        "copy",
        "-ac",
        str(ac_value),
        "-c:a",
        "aac",
        "-c:s",
        "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"reencode_audio failed for event {entry.event_id}: ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path)
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_AUDIO,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_remux_container(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """Container swap via ffmpeg ``-c copy``. Path extension differs.

    Writes ffmpeg's output to a ``<output>.tmp.<resolved_seed>`` sibling
    then atomically renames it over the final path. Re-hashes and
    re-probes the output, stashing both on ``ctx.post_phase_b_versions``
    for ``manifest_build.augment_versions`` to drain. Ensures the output
    parent directory exists before the rename, since changing the
    extension can imply a different parent in some scenarios.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-c",
        "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"remux_container failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.REMUX_CONTAINER,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path)
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REMUX_CONTAINER,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_edit_metadata(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """ffmpeg ``-c copy -map_metadata 0 -metadata k=v ...``.

    In-place edit (``input_path == output_path``). The ``fields`` dict
    on the journal state_delta is sorted before being emitted so the
    resulting argv (and therefore the ToolInvocation.command) is
    deterministic across runs with otherwise-equal inputs.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    fields = delta["fields"]
    if not isinstance(fields, dict):
        raise MediaActionError(
            f"edit_metadata.fields not a dict for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.EDIT_METADATA,
            cause=TypeError(f"fields type {type(fields).__name__}"),
        )
    fields_map = cast(dict[str, str], fields)
    metadata_args: list[str] = []
    for key, value in sorted(fields_map.items()):
        metadata_args.extend(["-metadata", f"{key}={value}"])
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-c",
        "copy",
        "-map_metadata",
        "0",
        *metadata_args,
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"edit_metadata failed for event {entry.event_id}: ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.EDIT_METADATA,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path)
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EDIT_METADATA,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_embed_subtitle(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """ffmpeg muxes the sidecar into the asset; unlinks the sidecar after success.

    The output container's extension selects the in-container subtitle
    codec via ``_subtitle_codec_for_container`` (mkv/webm → ``srt``;
    mp4/m4v/mov → ``mov_text``; others raise ValueError, which is
    wrapped in MediaActionError). The sidecar file is unlinked only
    after the atomic rename succeeds — if ffmpeg fails, the sidecar
    must remain on disk for the next attempt.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    sidecar_disk_path = ctx.library_root / str(delta["embedded_sidecar_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    container_ext = output_path.suffix.lstrip(".")
    try:
        subtitle_codec = _subtitle_codec_for_container(container_ext)
    except ValueError as exc:
        raise MediaActionError(
            f"embed_subtitle: unsupported output container {container_ext!r} "
            f"for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.EMBED_SUBTITLE,
            cause=exc,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-i",
        str(sidecar_disk_path),
        "-map",
        "0",
        "-map",
        "1",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        subtitle_codec,
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"embed_subtitle failed for event {entry.event_id}: ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.EMBED_SUBTITLE,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    sidecar_disk_path.unlink()
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path)
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EMBED_SUBTITLE,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_extract_subtitle(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """ffmpeg -map 0:s:m:language:<lang>? -c:s srt sidecar.srt.

    Output is always .srt regardless of asset container. No re-probe
    (asset bytes unchanged); hash only the new sidecar file.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    sidecar_path = ctx.library_root / str(delta["sidecar_path"])
    temp_output = _temp_sibling(sidecar_path, ctx.resolved_seed)
    language = str(delta["language"])
    # The optional "?" suffix tells ffmpeg "skip if no match" — combined
    # with a -map fallback, this gives the language-or-track-0 behavior.
    # In practice ffmpeg's stream-specifier matrix is fiddly; if the
    # language match misses, ffmpeg emits a warning and the fallback
    # -map covers it. The output is always .srt.
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        f"0:s:m:language:{language}?",
        "-map",
        "0:s:0",
        "-c:s",
        "srt",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"extract_subtitle failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.EXTRACT_SUBTITLE,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output.replace(sidecar_path)
    new_hash = _hash_file(sidecar_path)
    sidecar_id = str(delta["sidecar_id"])
    ctx.post_phase_b_sidecars[sidecar_id] = (new_hash, str(delta["sidecar_path"]))
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["sidecar_path"]),
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id=sidecar_id,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_update_sidecar(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """Regenerate the sidecar's bytes with a perturbed sub-seed.

    Per spec design decision #7, the perturbed seed includes event_id
    so consecutive updates on the same sidecar produce distinct bytes.

    Subtitle / NFO: pure Python; tool_invocation_index = None.
    Poster: invokes ffmpeg lavfi; tool_invocation_index populated.
    """
    delta = entry.state_delta
    sidecar_id = str(delta["sidecar_id"])
    sidecar_path = ctx.library_root / str(delta["sidecar_path"])
    temp_output = _temp_sibling(sidecar_path, ctx.resolved_seed)
    if ctx.sidecar_lookup is None:
        raise MediaActionError(
            "update_sidecar: ctx.sidecar_lookup is None",
            event_id=entry.event_id,
            action=TimelineActionName.UPDATE_SIDECAR,
            cause=RuntimeError("missing lookup"),
        )
    sidecar = ctx.sidecar_lookup(sidecar_id)
    if sidecar is None:
        raise MediaActionError(
            f"update_sidecar: sidecar_id {sidecar_id!r} not in manifest",
            event_id=entry.event_id,
            action=TimelineActionName.UPDATE_SIDECAR,
            cause=KeyError(sidecar_id),
        )
    asset = ctx.scenario_assets.get(sidecar.asset_id)
    if asset is None:
        raise MediaActionError(
            f"update_sidecar: asset {sidecar.asset_id!r} not in scenario",
            event_id=entry.event_id,
            action=TimelineActionName.UPDATE_SIDECAR,
            cause=KeyError(sidecar.asset_id),
        )
    kind = SidecarKind(sidecar.kind)
    started = time.monotonic_ns()
    invocation_index: int | None = None
    bytes_, argv = regenerate_sidecar(
        kind=kind,
        language=sidecar.language,
        sidecar_id=sidecar_id,
        resolved_seed=ctx.resolved_seed,
        event_id=entry.event_id,
        duration_s=asset.duration_seconds,
        output_path=temp_output,
    )
    if bytes_ is not None:
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        temp_output.write_bytes(bytes_)
    else:
        if argv is None:
            raise MediaActionError(
                f"update_sidecar: regenerate_sidecar returned no bytes and no argv "
                f"for event {entry.event_id}",
                event_id=entry.event_id,
                action=TimelineActionName.UPDATE_SIDECAR,
                cause=RuntimeError("missing argv"),
                asset_id=sidecar.asset_id,
            )
        invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
        invocation_index = len(ctx.invocations)
        ctx.invocations.append(invocation)
        if invocation.exit_code != 0:
            raise MediaActionError(
                f"update_sidecar (poster) failed for event {entry.event_id}: "
                f"ffmpeg exit {invocation.exit_code}",
                event_id=entry.event_id,
                action=TimelineActionName.UPDATE_SIDECAR,
                cause=RuntimeError(stderr_tail or "ffmpeg failed"),
                asset_id=sidecar.asset_id,
                tool_invocation_index=invocation_index,
            )
    temp_output.replace(sidecar_path)
    new_hash = _hash_file(sidecar_path)
    ctx.post_phase_b_sidecars[sidecar_id] = (new_hash, str(delta["sidecar_path"]))
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.UPDATE_SIDECAR,
        target_asset_id=sidecar.asset_id,
        input_path=str(delta["sidecar_path"]),  # input == output for update
        output_path=str(delta["sidecar_path"]),
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id=sidecar_id,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


# Dispatcher table. Other handlers added in subsequent Sprint 7 tasks.
_HANDLERS: Final[dict[TimelineActionName, Callable[[_MediaContext, JournalEntry], MediaAction]]] = {
    TimelineActionName.REENCODE_VIDEO: _apply_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _apply_reencode_audio,
    TimelineActionName.REMUX_CONTAINER: _apply_remux_container,
    TimelineActionName.EDIT_METADATA: _apply_edit_metadata,
    TimelineActionName.EMBED_SUBTITLE: _apply_embed_subtitle,
    TimelineActionName.EXTRACT_SUBTITLE: _apply_extract_subtitle,
    TimelineActionName.UPDATE_SIDECAR: _apply_update_sidecar,
}


def apply_media_action(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """Dispatch one journal entry to its media handler.

    Raises:
        MediaActionError: ffmpeg non-zero exit, ffprobe parse failure,
            OSError during the rename, or no handler registered for the
            entry's action.
    """
    action = TimelineActionName(entry.action)
    handler = _HANDLERS.get(action)
    if handler is None:
        raise MediaActionError(
            f"no media handler for action {action.value!r}",
            event_id=entry.event_id,
            action=action,
            cause=RuntimeError("no dispatch"),
        )
    return handler(ctx, entry)


_MEDIA_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.UPDATE_SIDECAR,
    }
)


_STDLIB_ACTIONS: Final[frozenset[TimelineActionName]] = SUPPORTED_S6_ACTIONS | frozenset(
    {TimelineActionName.REMOVE_SIDECAR}
)


SUPPORTED_S7_ACTIONS: Final[frozenset[TimelineActionName]] = _STDLIB_ACTIONS | _MEDIA_ACTIONS
# add_file remains excluded; preflight rejects it with
# E_MATERIALIZE_TIMELINE_UNSUPPORTED.
