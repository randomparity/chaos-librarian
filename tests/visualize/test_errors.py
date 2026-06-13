"""Error-type contract for the visualizer."""

from __future__ import annotations

from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    MissingArtifactError,
    ScenarioRevalidationError,
)


def test_revalidation_error_names_codes_and_contract_hint() -> None:
    err = ScenarioRevalidationError(codes=["E_SCHEMA_VERSION"])
    assert isinstance(err, ChaosLibrarianError)
    assert "E_SCHEMA_VERSION" in str(err)
    assert "contract" in str(err).lower()
    assert err.codes == ["E_SCHEMA_VERSION"]


def test_missing_artifact_names_artifact_and_producer() -> None:
    err = MissingArtifactError(artifact="replay.json", produced_by="chaos-librarian plan")
    assert isinstance(err, ChaosLibrarianError)
    assert "replay.json" in str(err)
    assert "chaos-librarian plan" in str(err)


def test_divergence_cites_position_and_both_ids() -> None:
    err = JournalDivergenceError(position=4, disk_event_id="move_009", replay_event_id="move_005")
    assert isinstance(err, ChaosLibrarianError)
    assert "4" in str(err)
    assert "move_009" in str(err)
    assert "move_005" in str(err)
    assert err.position == 4


def test_corrupt_line_cites_line_number() -> None:
    err = JournalCorruptLineError(line=7, detail="expecting value")
    assert isinstance(err, ChaosLibrarianError)
    assert "7" in str(err)
    assert err.line == 7
    assert err.detail == "expecting value"
