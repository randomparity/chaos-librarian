"""Visualizer error types.

All subclasses of ``ChaosLibrarianError`` so the script entry point can
catch one base class and exit with an actionable message.
"""

from __future__ import annotations

from chaos_librarian.errors import ChaosLibrarianError


class MissingArtifactError(ChaosLibrarianError):
    """A required run-dir artifact is absent."""

    def __init__(self, *, artifact: str, produced_by: str) -> None:
        super().__init__(f"missing required artifact {artifact!r} — produced by `{produced_by}`")
        self.artifact = artifact
        self.produced_by = produced_by


class JournalDivergenceError(ChaosLibrarianError):
    """The on-disk journal disagrees with the replayed sequence at a position."""

    def __init__(self, *, position: int, disk_event_id: str, replay_event_id: str) -> None:
        super().__init__(
            f"journal diverges at position {position}: on-disk event_id "
            f"{disk_event_id!r} != replayed event_id {replay_event_id!r}"
        )
        self.position = position
        self.disk_event_id = disk_event_id
        self.replay_event_id = replay_event_id


class JournalCorruptLineError(ChaosLibrarianError):
    """A non-final journal line failed to parse (corruption, not a torn write)."""

    def __init__(self, *, line: int, detail: str) -> None:
        super().__init__(f"journal.jsonl line {line} is unparseable: {detail}")
        self.line = line
        self.detail = detail


class ScenarioRevalidationError(ChaosLibrarianError):
    """The run dir's embedded scenario fails re-validation against this contract.

    Mirrors the guard ``replay_plan_bundle`` applies: an older run dir can
    embed a scenario that no longer validates against the current contract
    version. Raised as a ``ChaosLibrarianError`` so the script entry point
    reports it cleanly instead of leaking a Pydantic ``ValidationError``.
    """

    def __init__(self, *, codes: list[str]) -> None:
        super().__init__(
            f"embedded scenario failed re-validation ({codes}); the run dir "
            "likely predates the current contract version — re-run it on this build"
        )
        self.codes = codes


__all__ = [
    "JournalCorruptLineError",
    "JournalDivergenceError",
    "MissingArtifactError",
    "ScenarioRevalidationError",
]
