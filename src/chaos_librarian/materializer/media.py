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

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import Asset

__all__ = ["_subtitle_codec_for_container"]


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
