"""Phase-B media dispatcher — ffmpeg-backed handlers for byte-changing events.

Parallel to Sprint 6's ``materializer/filesystem.py``: one handler per
media action, each reads every path from the journal entry's
``state_delta`` and writes through an atomic-rename temp-file.

The orchestrator in ``materializer/run.py`` walks the journal once and
dispatches each entry to ``apply_media_action`` here OR to the stdlib
dispatcher in ``filesystem.py``. See ``materializer.actions`` for the
routing action sets.

Per-action ffmpeg sketches are in the Sprint 7 spec
§"Per-action behavior" table.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import MediaAction, ToolInvocation
from chaos_librarian.contract.scenario import (
    AUDIO_CHANNEL_COUNTS_BY_NAME,
    Asset,
    SidecarKind,
    TimelineActionName,
)
from chaos_librarian.materializer.actions import (
    SUPPORTED_S7_ACTIONS,
)
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.phase_b.content import hash_file, temp_sibling
from chaos_librarian.materializer.phase_b.sidecar_bytes import (
    cue_payload,
    encode_subtitle_body,
    poster_ffmpeg_argv,
    regenerate_sidecar,
    render_nfo,
)
from chaos_librarian.materializer.tooling.ffmpeg import BITEXACT_FLAGS, run_ffmpeg
from chaos_librarian.materializer.tooling.probe import probe_file
from chaos_librarian.materializer.tooling.recipes import srt_payload
from chaos_librarian.media_matrix import AUDIO_ENCODER_BY_CODEC


def _coerce_str_keyed_dict(value: object) -> dict[str, object] | None:
    """Return ``value`` as ``dict[str, object]`` if every key is a string."""
    if not isinstance(value, dict):
        return None
    blob: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        blob[key] = item
    return blob


__all__ = [
    "SUPPORTED_S7_ACTIONS",
    "LiveSidecar",
    "MediaPhaseBContext",
    "_subtitle_codec_for_container",
    "apply_media_action",
    "make_media_phase_b_context",
    "supports_media_action",
]


@dataclass(frozen=True, slots=True)
class LiveSidecar:
    """The metadata ``update_sidecar`` needs to regenerate a sidecar's bytes.

    Tracked live across the phase-B journal walk so ``update_sidecar`` can
    resolve a sidecar that was created (or extracted) earlier in the same walk
    even when a later ``embed_subtitle`` / ``remove_sidecar`` drops it from the
    final manifest (issue #112).
    """

    kind: SidecarKind
    language: str | None
    asset_id: str
    # Authored content knobs (scenario v24). Carried so update_sidecar
    # regenerates with the same encoding / body / media_type rather than
    # reverting to the kind's default. None for sidecars seeded from the
    # initial manifest (which has no authoring inputs).
    encoding: str | None = None
    body: str | None = None
    media_type: str | None = None


_SUBTITLE_CODEC_BY_CONTAINER: Final[dict[str, str]] = {
    "mkv": "srt",
    "webm": "srt",
    "mp4": "mov_text",
    "m4v": "mov_text",
    "mov": "mov_text",
}


# ffmpeg's ``-ac`` flag requires an integer channel count; scenario authors
# write natural layout names such as ``"stereo"`` / ``"5.1"``.
_CHANNEL_COUNT_BY_NAME: Final = AUDIO_CHANNEL_COUNTS_BY_NAME


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
class MediaPhaseBContext:
    """Per-run state threaded through every media handler.

    Mirrors ``filesystem.FilesystemPhaseBContext`` but carries extra fields the
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
    # Live sidecar metadata keyed by sidecar_id. Seeded from the sidecars that
    # exist at the start of the phase-B walk and updated as create_sidecar /
    # extract_subtitle entries are dispatched, so update_sidecar can resolve a
    # sidecar that never survives to the final manifest (issue #112).
    live_sidecars: dict[str, LiveSidecar] = field(default_factory=dict)


def make_media_phase_b_context(
    *,
    library_root: Path,
    scenario_assets: Mapping[str, Asset],
    resolved_seed: int,
    ffmpeg_version: str,
    ffprobe_version: str,
    invocations: list[ToolInvocation],
    initial_sidecars: Iterable[ManifestSidecar],
) -> MediaPhaseBContext:
    live_sidecars: dict[str, LiveSidecar] = {}
    for sidecar in initial_sidecars:
        live_sidecars[sidecar.id] = LiveSidecar(
            kind=SidecarKind(sidecar.kind),
            language=sidecar.language,
            asset_id=sidecar.asset_id,
        )
    return MediaPhaseBContext(
        library_root=library_root,
        scenario_assets=scenario_assets,
        resolved_seed=resolved_seed,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        invocations=invocations,
        live_sidecars=live_sidecars,
    )


def supports_media_action(action: TimelineActionName) -> bool:
    return action in _HANDLERS


_RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}


def _resolution_pixels_for(resolution: str) -> tuple[int, int]:
    """Return the ``(width, height)`` pixels for a scenario resolution name.

    Raises ValueError when ``resolution`` isn't a known name; the caller
    wraps that in a MediaActionError so the user sees
    E_MATERIALIZE_MEDIA_FAILED instead of ffmpeg silently emitting SD.
    """
    pixels = _RESOLUTION_PIXELS.get(resolution)
    if pixels is None:
        raise ValueError(
            f"unknown video resolution {resolution!r}; supported: {sorted(_RESOLUTION_PIXELS)}"
        )
    return pixels


@dataclass(frozen=True, slots=True)
class _VersionOutput:
    version_id: str
    content_hash: str


def _target_asset_id(entry: JournalEntry) -> str | None:
    return entry.target_ids[0] if entry.target_ids else None


def _audio_encoder_for_reencode(ctx: MediaPhaseBContext, entry: JournalEntry) -> str:
    asset_id = _target_asset_id(entry)
    if asset_id is None:
        raise MediaActionError(
            f"reencode_audio: missing target asset for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=ValueError("target_ids is empty"),
            asset_id=None,
        )
    asset = ctx.scenario_assets.get(asset_id)
    if asset is None:
        raise MediaActionError(
            f"reencode_audio: asset {asset_id!r} not in scenario",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=KeyError(asset_id),
            asset_id=asset_id,
        )
    if asset.video is not None:
        return "aac"
    if len(asset.audio) != 1:
        raise MediaActionError(
            f"reencode_audio: asset {asset.id!r} does not have exactly one audio stream",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=ValueError("audio stream count unsupported"),
            asset_id=asset.id,
        )
    codec = asset.audio[0].codec
    encoder = AUDIO_ENCODER_BY_CODEC.get(codec)
    if encoder is None:
        raise MediaActionError(
            f"reencode_audio: unsupported audio codec {codec!r} for asset {asset.id!r}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=ValueError(f"unsupported audio codec: {codec!r}"),
            asset_id=asset.id,
        )
    return encoder


def _run_ffmpeg_checked(
    ctx: MediaPhaseBContext,
    *,
    argv: list[str],
    entry: JournalEntry,
    action: TimelineActionName,
    failure_label: str,
    asset_id: str | None,
) -> int:
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"{failure_label} failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=action,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=asset_id,
            tool_invocation_index=invocation_index,
        )
    return invocation_index


def _finalize_version_output(
    ctx: MediaPhaseBContext,
    *,
    temp_output: Path,
    output_path: Path,
    output_version_id: str,
) -> _VersionOutput:
    temp_output.replace(output_path)
    new_hash = hash_file(output_path)
    probed = probe_file(output_path)
    ctx.post_phase_b_versions[output_version_id] = (new_hash, probed)
    return _VersionOutput(version_id=output_version_id, content_hash=new_hash)


def _apply_reencode_video(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
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
    temp_output = temp_sibling(output_path, ctx.resolved_seed)
    resolution = str(delta["resolution"])
    try:
        width, height = _resolution_pixels_for(resolution)
    except ValueError as exc:
        raise MediaActionError(
            f"reencode_video: unknown resolution {resolution!r} for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_VIDEO,
            cause=exc,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
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
    invocation_index = _run_ffmpeg_checked(
        ctx,
        argv=argv,
        entry=entry,
        action=TimelineActionName.REENCODE_VIDEO,
        failure_label="reencode_video",
        asset_id=_target_asset_id(entry),
    )
    version = _finalize_version_output(
        ctx,
        temp_output=temp_output,
        output_path=output_path,
        output_version_id=entry.output_version_ids[0],
    )
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_VIDEO,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=version.version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=version.content_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_reencode_audio(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """Re-encode audio in place. from_channels is descriptive; -ac uses to_channels."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = temp_sibling(output_path, ctx.resolved_seed)
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
    audio_encoder = _audio_encoder_for_reencode(ctx, entry)
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
        audio_encoder,
        "-c:s",
        "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation_index = _run_ffmpeg_checked(
        ctx,
        argv=argv,
        entry=entry,
        action=TimelineActionName.REENCODE_AUDIO,
        failure_label="reencode_audio",
        asset_id=_target_asset_id(entry),
    )
    version = _finalize_version_output(
        ctx,
        temp_output=temp_output,
        output_path=output_path,
        output_version_id=entry.output_version_ids[0],
    )
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_AUDIO,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=version.version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=version.content_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_remux_container(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """Container swap via ffmpeg ``-c copy``. Path extension differs.

    Writes ffmpeg's output to a ``<output>.tmp.<resolved_seed>`` sibling
    then atomically renames it over the final path. Re-hashes and
    re-probes the output, stashing both on ``ctx.post_phase_b_versions``
    for ``manifest_build.augment_versions`` to drain. Ensures the output
    parent directory exists before the rename, since changing the
    extension can imply a different parent in some scenarios.

    The old-extension input file is unlinked AFTER the new container is
    in place at ``output_path`` — preserving the crash-safety guarantee
    that a half-finished remux leaves both files on disk (never zero).
    The unlink is skipped when ``input_path`` resolves to the same
    absolute path as ``output_path`` (a same-extension remux is not a
    real scenario today, but the guard documents the invariant). Any
    OSError from the unlink propagates (fail loud, #60).
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = temp_sibling(output_path, ctx.resolved_seed)
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
    invocation_index = _run_ffmpeg_checked(
        ctx,
        argv=argv,
        entry=entry,
        action=TimelineActionName.REMUX_CONTAINER,
        failure_label="remux_container",
        asset_id=_target_asset_id(entry),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    version = _finalize_version_output(
        ctx,
        temp_output=temp_output,
        output_path=output_path,
        output_version_id=entry.output_version_ids[0],
    )
    if input_path.resolve() != output_path.resolve():
        input_path.unlink(missing_ok=False)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REMUX_CONTAINER,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=version.version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=version.content_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_edit_metadata(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """ffmpeg ``-c copy -map_metadata 0 -metadata k=v ...``.

    In-place edit (``input_path == output_path``). The ``fields`` dict
    on the journal state_delta is sorted before being emitted so the
    resulting argv (and therefore the ToolInvocation.command) is
    deterministic across runs with otherwise-equal inputs.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = temp_sibling(output_path, ctx.resolved_seed)
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
    invocation_index = _run_ffmpeg_checked(
        ctx,
        argv=argv,
        entry=entry,
        action=TimelineActionName.EDIT_METADATA,
        failure_label="edit_metadata",
        asset_id=_target_asset_id(entry),
    )
    version = _finalize_version_output(
        ctx,
        temp_output=temp_output,
        output_path=output_path,
        output_version_id=entry.output_version_ids[0],
    )
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EDIT_METADATA,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=version.version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=version.content_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _apply_embed_subtitle(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
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
    temp_output = temp_sibling(output_path, ctx.resolved_seed)
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
    invocation_index = _run_ffmpeg_checked(
        ctx,
        argv=argv,
        entry=entry,
        action=TimelineActionName.EMBED_SUBTITLE,
        failure_label="embed_subtitle",
        asset_id=_target_asset_id(entry),
    )
    version = _finalize_version_output(
        ctx,
        temp_output=temp_output,
        output_path=output_path,
        output_version_id=entry.output_version_ids[0],
    )
    sidecar_disk_path.unlink()
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EMBED_SUBTITLE,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=version.version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=version.content_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


def _probe_subtitle_index_for_language(
    ctx: MediaPhaseBContext, input_path: Path, language: str
) -> int:
    """Return the subtitle-stream index whose tags.language matches.

    Indexing is relative to subtitle streams only (matching ffmpeg's
    ``-map 0:s:<idx>`` semantics — the 0th subtitle stream is ``0:s:0``,
    not the absolute stream index). Falls back to ``0`` when no track's
    language tag matches ``language`` (per spec design decision #8).

    A ``ToolInvocation`` for the ffprobe call is appended to
    ``ctx.invocations`` BEFORE any RuntimeError is raised so the audit
    trail captures failed probes too (closes #61).

    Raises:
        RuntimeError: ffprobe exited non-zero or produced unparseable
            JSON. The caller (the extract_subtitle handler) wraps the
            propagated exception in a MediaActionError.
    """
    argv = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "error",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index:stream_tags=language",
        "-of",
        "json",
        str(input_path),
    ]
    started = time.monotonic_ns()
    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=15.0,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    duration_ns = time.monotonic_ns() - started
    ctx.invocations.append(
        ToolInvocation(
            tool="ffprobe",
            version=ctx.ffprobe_version,
            command=list(argv),
            exit_code=completed.returncode,
            duration_ns=duration_ns,
        )
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffprobe (subtitle index) exit {completed.returncode} on {input_path}: "
            f"{(completed.stderr or '')[-512:]}"
        )
    try:
        raw: object = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"ffprobe (subtitle index) stdout was not valid JSON for {input_path}"
        ) from exc
    payload = _coerce_str_keyed_dict(raw)
    if payload is None:
        return 0
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return 0
    target = language.lower()
    for idx, stream in enumerate(streams):
        stream_blob = _coerce_str_keyed_dict(stream)
        if stream_blob is None:
            continue
        tags = _coerce_str_keyed_dict(stream_blob.get("tags"))
        if tags is None:
            continue
        lang = tags.get("language")
        if isinstance(lang, str) and lang.lower() == target:
            return idx
    return 0


def _apply_extract_subtitle(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """ffmpeg -map 0:s:<idx> -c:s srt sidecar.srt.

    Output is always .srt regardless of asset container. No re-probe
    (asset bytes unchanged); hash only the new sidecar file.

    The subtitle stream index is resolved by probing the asset's
    subtitle tracks with ffprobe and matching ``tags.language`` against
    ``event.language``. Falls back to track 0 on no match (per spec
    design decision #8). Earlier revisions used
    ``-map 0:s:m:language:<lang>? -map 0:s:0`` but ffmpeg 8.x rejects
    that metadata stream-specifier combination (#59).
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    sidecar_path = ctx.library_root / str(delta["sidecar_path"])
    temp_output = temp_sibling(sidecar_path, ctx.resolved_seed)
    language = str(delta["language"])
    try:
        subtitle_index = _probe_subtitle_index_for_language(ctx, input_path, language)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise MediaActionError(
            f"extract_subtitle: ffprobe failed selecting subtitle index for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.EXTRACT_SUBTITLE,
            cause=exc,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        f"0:s:{subtitle_index}",
        "-c:s",
        "srt",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation_index = _run_ffmpeg_checked(
        ctx,
        argv=argv,
        entry=entry,
        action=TimelineActionName.EXTRACT_SUBTITLE,
        failure_label="extract_subtitle",
        asset_id=_target_asset_id(entry),
    )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output.replace(sidecar_path)
    new_hash = hash_file(sidecar_path)
    sidecar_id = str(delta["sidecar_id"])
    ctx.post_phase_b_sidecars[sidecar_id] = (new_hash, str(delta["sidecar_path"]))
    ctx.live_sidecars[sidecar_id] = LiveSidecar(
        kind=SidecarKind.SUBTITLE, language=language, asset_id=entry.target_ids[0]
    )
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


def _apply_update_sidecar(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """Regenerate the sidecar's bytes with a perturbed sub-seed.

    Per spec design decision #7, the perturbed seed includes event_id
    so consecutive updates on the same sidecar produce distinct bytes.

    Subtitle / NFO: pure Python; tool_invocation_index = None.
    Poster: invokes ffmpeg lavfi; tool_invocation_index populated.
    """
    delta = entry.state_delta
    sidecar_id = str(delta["sidecar_id"])
    sidecar_path = ctx.library_root / str(delta["sidecar_path"])
    temp_output = temp_sibling(sidecar_path, ctx.resolved_seed)
    sidecar = ctx.live_sidecars.get(sidecar_id)
    if sidecar is None:
        raise MediaActionError(
            f"update_sidecar: sidecar_id {sidecar_id!r} is not a live sidecar",
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
    started = time.monotonic_ns()
    invocation_index: int | None = None
    bytes_, argv = regenerate_sidecar(
        kind=sidecar.kind,
        language=sidecar.language,
        sidecar_id=sidecar_id,
        resolved_seed=ctx.resolved_seed,
        event_id=entry.event_id,
        duration_s=asset.duration_seconds,
        output_path=temp_output,
        encoding=sidecar.encoding,
        body=sidecar.body,
        media_type=sidecar.media_type,
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
        invocation_index = _run_ffmpeg_checked(
            ctx,
            argv=argv,
            entry=entry,
            action=TimelineActionName.UPDATE_SIDECAR,
            failure_label="update_sidecar (poster)",
            asset_id=sidecar.asset_id,
        )
    temp_output.replace(sidecar_path)
    new_hash = hash_file(sidecar_path)
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


def _apply_create_sidecar(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """Create a sidecar file with bytes appropriate to ``state_delta['kind']``.

    Subtitle → ``srt_payload`` (pure Python). NFO → ``render_nfo`` (pure
    Python). Poster → ``poster_ffmpeg_argv`` (lavfi color source via
    ffmpeg). All three kinds use the standard atomic-rename via
    ``temp_sibling`` and stash ``(content_hash, path)`` on
    ``ctx.post_phase_b_sidecars`` so ``augment_updated_sidecars`` can
    stamp the engine-allocated ``ManifestSidecar`` row.

    Earlier revisions wrote SRT bytes unconditionally — independent of
    ``kind`` — so ``Quasar.poster.png`` and ``Quasar.nfo`` shipped with
    SRT contents on disk (PR #63 adversarial review, finding #1).
    """
    delta = entry.state_delta
    asset_id = entry.target_ids[0]
    sidecar_id = str(delta["sidecar_id"])
    sidecar_path_str = str(delta["sidecar_path"])
    sidecar_path = ctx.library_root / sidecar_path_str
    kind = SidecarKind(str(delta["kind"]))
    raw_language = delta.get("language")
    language = str(raw_language) if isinstance(raw_language, str) else None
    encoding = delta.get("encoding")
    encoding = str(encoding) if isinstance(encoding, str) else None
    raw_body = delta.get("body")
    body_text = str(raw_body) if isinstance(raw_body, str) else None
    media_type = delta.get("media_type")
    media_type = str(media_type) if isinstance(media_type, str) else None
    temp_output = temp_sibling(sidecar_path, ctx.resolved_seed)
    asset = ctx.scenario_assets[asset_id]
    started = time.monotonic_ns()
    invocation_index: int | None = None
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    if kind == SidecarKind.SUBTITLE:
        if language is None:
            raise MediaActionError(
                f"create_sidecar (subtitle) missing language for event {entry.event_id}",
                event_id=entry.event_id,
                action=TimelineActionName.CREATE_SIDECAR,
                cause=ValueError("language is None"),
                asset_id=asset_id,
            )
        text = srt_payload(
            language=language,
            duration_s=asset.duration_seconds,
            seed=ctx.resolved_seed,
        )
        temp_output.write_bytes(encode_subtitle_body(text, encoding))
    elif kind == SidecarKind.NFO:
        if body_text is not None:
            temp_output.write_bytes(body_text.encode("utf-8"))
        else:
            temp_output.write_bytes(render_nfo(sidecar_id=sidecar_id))
    elif kind == SidecarKind.CUE:
        temp_output.write_bytes(cue_payload(body=body_text, sidecar_id=sidecar_id))
    elif kind == SidecarKind.POSTER:
        argv = poster_ffmpeg_argv(
            output_path=temp_output,
            resolved_seed=ctx.resolved_seed,
            sidecar_id=sidecar_id,
            media_type=media_type,
        )
        invocation_index = _run_ffmpeg_checked(
            ctx,
            argv=argv,
            entry=entry,
            action=TimelineActionName.CREATE_SIDECAR,
            failure_label="create_sidecar (poster)",
            asset_id=asset_id,
        )
    else:  # pragma: no cover — SidecarKind is exhaustive
        raise MediaActionError(
            f"create_sidecar: unknown kind {kind!r} for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.CREATE_SIDECAR,
            cause=ValueError(f"unknown kind {kind!r}"),
            asset_id=asset_id,
        )
    temp_output.replace(sidecar_path)
    new_hash = hash_file(sidecar_path)
    ctx.post_phase_b_sidecars[sidecar_id] = (new_hash, sidecar_path_str)
    ctx.live_sidecars[sidecar_id] = LiveSidecar(
        kind=kind,
        language=language,
        asset_id=asset_id,
        encoding=encoding,
        body=body_text,
        media_type=media_type,
    )
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.CREATE_SIDECAR,
        target_asset_id=asset_id,
        input_path=sidecar_path_str,
        output_path=sidecar_path_str,
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id=sidecar_id,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


# Dispatcher table. Other handlers added in subsequent Sprint 7 tasks.
_HANDLERS: Final[
    dict[TimelineActionName, Callable[[MediaPhaseBContext, JournalEntry], MediaAction]]
] = {
    TimelineActionName.REENCODE_VIDEO: _apply_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _apply_reencode_audio,
    TimelineActionName.REMUX_CONTAINER: _apply_remux_container,
    TimelineActionName.EDIT_METADATA: _apply_edit_metadata,
    TimelineActionName.EMBED_SUBTITLE: _apply_embed_subtitle,
    TimelineActionName.EXTRACT_SUBTITLE: _apply_extract_subtitle,
    TimelineActionName.UPDATE_SIDECAR: _apply_update_sidecar,
    TimelineActionName.CREATE_SIDECAR: _apply_create_sidecar,
}


def apply_media_action(ctx: MediaPhaseBContext, entry: JournalEntry) -> MediaAction:
    """Dispatch one journal entry to its media handler.

    Raises:
        MediaActionError: ffmpeg non-zero exit, ffprobe parse failure, no
            handler registered for the entry's action, or the first exception
            raised by a media handler.

    Handler exceptions are wrapped here rather than propagating bare. Without
    this wrapper the orchestrator's phase-B failure path — keyed on
    ``MediaActionError`` — never runs and ``library/`` is left half-mutated
    with the sentinel stuck at ``IN_PROGRESS`` (PR #63 adversarial review,
    finding #3).
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
    try:
        return handler(ctx, entry)
    except MediaActionError:
        raise
    except Exception as exc:
        raise MediaActionError(
            f"{action.value} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id,
            action=action,
            cause=exc,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
