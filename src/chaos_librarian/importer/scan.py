"""Directory scan for the ``import`` command (issue #105 / ADR 0012).

Classifies files by extension against a real-library media vocabulary —
deliberately wider than the synthesis matrix, because import exists for
files the matrix cannot represent. Extension matching is case-insensitive;
unrecognized files are reported as skips, never errors.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from chaos_librarian.media_matrix import IMPORT_VIDEO_CONTAINERS

__all__ = [
    "AUDIO_SUFFIXES",
    "NFO_SUFFIXES",
    "POSTER_STEM_PREFIXES",
    "POSTER_SUFFIXES",
    "SUBTITLE_EXTENSIONS_BY_SUFFIX",
    "VIDEO_SUFFIXES",
    "ScannedFile",
    "SkipRecord",
    "scan_directory",
]

# Dotted, lowercase suffixes; scan compares Path.suffix.lower().
VIDEO_SUFFIXES: Final[frozenset[str]] = frozenset(
    "." + container for container in IMPORT_VIDEO_CONTAINERS
)
AUDIO_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".flac", ".mp3", ".m4a", ".wav", ".ogg", ".opus"}
)
SUBTITLE_EXTENSIONS_BY_SUFFIX: Final[dict[str, str]] = {
    ".srt": "srt",
    ".ass": "ass",
    ".ssa": "ssa",
}
NFO_SUFFIXES: Final[frozenset[str]] = frozenset({".nfo"})
POSTER_SUFFIXES: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
POSTER_STEM_PREFIXES: Final[tuple[str, ...]] = ("poster", "folder", "cover")


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """One classified input file."""

    path: Path  # absolute, as found
    kind: str  # "video" | "audio" | "subtitle" | "nfo" | "poster"


@dataclass(frozen=True, slots=True)
class SkipRecord:
    """One dropped input with its observable reason (spec skip taxonomy)."""

    path: Path
    reason: str


def classify(path: Path) -> str | None:
    """Return the file kind by case-insensitive suffix, or None."""
    suffix = path.suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in SUBTITLE_EXTENSIONS_BY_SUFFIX:
        return "subtitle"
    if suffix in NFO_SUFFIXES:
        return "nfo"
    if suffix in POSTER_SUFFIXES and path.name.lower().startswith(POSTER_STEM_PREFIXES):
        return "poster"
    return None


def scan_directory(root: Path) -> tuple[list[ScannedFile], list[SkipRecord]]:
    """Walk ``root`` in sorted order, classifying every file.

    Hidden directories and symlinked directories are not entered. Every file
    is either classified or recorded as skipped with reason ``unrecognized``.
    """
    scanned: list[ScannedFile] = []
    skipped: list[SkipRecord] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts[:-1]):
            continue  # hidden directory: not entered
        kind = classify(path) if path.is_file() else None
        if kind is None:
            skipped.append(SkipRecord(path=path, reason="unrecognized"))
            continue
        scanned.append(ScannedFile(path=path, kind=kind))
    return scanned, skipped
