"""ffprobe + digest for scanned media files (issue #105 / ADR 0012)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.importer.scan import ScannedFile, SkipRecord
from chaos_librarian.materializer.tooling.probe import probe_file

__all__ = ["ProbedInput", "probe_inputs"]


@dataclass(frozen=True, slots=True)
class ProbedInput:
    """One media file with its probe and content digest."""

    scanned: ScannedFile
    probed: ProbedMedia
    sha256: str  # bare hex; bundle name uses f"{sha256}.{container}"


def probe_inputs(files: list[ScannedFile]) -> tuple[list[ProbedInput], list[SkipRecord]]:
    """Probe each media-kind file in order; failures become ``probe_failed`` skips.

    A file that cannot be probed never aborts the import — it is reported and
    dropped, so one corrupt file costs nothing but its row in the report.
    """
    probed: list[ProbedInput] = []
    skipped: list[SkipRecord] = []
    for scanned in files:
        try:
            media = probe_file(scanned.path)
            with scanned.path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
        except Exception as exc:
            skipped.append(
                SkipRecord(
                    path=scanned.path,
                    reason=f"probe_failed: {type(exc).__name__}: {exc}",
                )
            )
            continue
        probed.append(ProbedInput(scanned=scanned, probed=media, sha256=digest))
    return probed, skipped
