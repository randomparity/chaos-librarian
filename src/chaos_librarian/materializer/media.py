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
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import MediaAction, ToolInvocation
from chaos_librarian.contract.scenario import Asset, TimelineActionName
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.ffmpeg import BITEXACT_FLAGS, run_ffmpeg
from chaos_librarian.materializer.probe import probe_file

__all__ = ["_MediaContext", "_subtitle_codec_for_container", "apply_media_action"]


_SUBTITLE_CODEC_BY_CONTAINER: Final[dict[str, str]] = {
    "mkv": "srt",
    "webm": "srt",
    "mp4": "mov_text",
    "m4v": "mov_text",
    "mov": "mov_text",
}


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


_RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}


def _temp_sibling(output_path: Path, resolved_seed: int) -> Path:
    """Return ``<output>.tmp.<resolved_seed>`` Path."""
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


# Dispatcher table. Other handlers added in subsequent Sprint 7 tasks.
_HANDLERS: Final[dict[TimelineActionName, Callable[[_MediaContext, JournalEntry], MediaAction]]] = {
    TimelineActionName.REENCODE_VIDEO: _apply_reencode_video,
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
