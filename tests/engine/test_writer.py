"""Tests for chaos_librarian.engine.writer."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.engine import writer as writer_mod
from chaos_librarian.engine.writer import write_fixture

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _empty_artifacts() -> tuple[PlanArtifacts, bytes]:
    empty_manifest = Manifest(
        schema_version=1,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )
    bundle = PlanOnlyReplayBundle(
        schema_version=2,
        chaos_librarian_version="0.0.0",
        scenario="schema_version: 1\n",
        run_id=_RUN_ID,
        resolved_seed=1,
        applied_events=0,
        journal_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        execution_trace=[],
        execution_mode=ExecutionMode.PLAN_ONLY,
    )
    sentinel = RunSentinel(
        run_id=_RUN_ID,
        schema_version=1,
        created_by="chaos-librarian 0.0.0",
        created_at=None,
    )
    artifacts = PlanArtifacts(
        initial_manifest=empty_manifest,
        current_manifest=empty_manifest,
        journal=(),
        replay_bundle=bundle,
        validation_report=ValidationReport(schema_version=1, scenario_id="t", ok=True, issues=[]),
        sentinel=sentinel,
    )
    return artifacts, b"schema_version: 1\n"


class TestWriteFixtureFileSet:
    """write_fixture writes exactly seven files at the run directory.

    WHY: any extra file becomes part of the contract; any missing file
    breaks the fixture-layout doc. The seven-file set is the contract.
    """

    def test_creates_expected_files(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        files = sorted(p.name for p in out.iterdir())
        assert files == [
            ".chaos-librarian-run",
            "journal.jsonl",
            "manifest.current.json",
            "manifest.initial.json",
            "replay.json",
            "scenario.yaml",
            "validation.json",
        ]

    def test_scenario_yaml_is_verbatim(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        assert (out / "scenario.yaml").read_bytes() == scenario_bytes

    def test_sentinel_round_trips_via_pydantic(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        loaded = RunSentinel.model_validate_json((out / ".chaos-librarian-run").read_text())
        assert loaded.run_id == _RUN_ID
        assert loaded.created_at is None

    def test_journal_is_jsonl_with_trailing_newline(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        text = (out / "journal.jsonl").read_text()
        # Empty journal: empty file. Non-empty journals end in "\n".
        assert text == ""


class TestWriteFixtureRefusesExistingDir:
    """write_fixture refuses a pre-existing target directory.

    WHY: ``--out`` callback also refuses; this is defense in depth. A
    scenario where the callback is bypassed (programmatic call from a
    library) still must not clobber.
    """

    def test_existing_dir_raises(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        out.mkdir()
        artifacts, scenario_bytes = _empty_artifacts()
        with pytest.raises(FileExistsError):
            write_fixture(out, artifacts, scenario_bytes)


class TestWriteFixtureDeterministicBytes:
    """Two writes of the same artifacts produce byte-identical files.

    WHY: this is the headline Sprint 3 invariant. The artifacts dataclass
    is frozen, so equal inputs must yield equal bytes on disk.
    """

    def test_byte_equal(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(a, artifacts, scenario_bytes)
        write_fixture(b, artifacts, scenario_bytes)
        for name in [
            ".chaos-librarian-run",
            "manifest.current.json",
            "manifest.initial.json",
            "replay.json",
            "validation.json",
            "scenario.yaml",
            "journal.jsonl",
        ]:
            assert (a / name).read_bytes() == (b / name).read_bytes(), name


class TestPlanOnlyExcludesVolatileFields:
    """The plan-only replay bundle on disk omits ``created_at``.

    WHY: the bundle's plan-only variant has no created_at field; exclude_none
    keeps materialize fields from leaking when a future code path sets None.
    """

    def test_replay_json_has_no_created_at(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        payload = json.loads((out / "replay.json").read_text())
        assert "created_at" not in payload
        assert "toolchain" not in payload


class TestWriteFixtureIsTransactional:
    """A mid-write failure leaves no fixture at all.

    WHY: future tools treat the sentinel as the trust boundary. A partial
    write that landed a sentinel would lie about the contents.
    """

    def test_failure_leaves_no_out_dir(self, tmp_path: Path, monkeypatch) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()

        call_count = {"n": 0}
        real_emit_json = writer_mod._emit_json

        def flaky_emit_json(model, target):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise OSError("simulated disk full")
            real_emit_json(model, target)

        monkeypatch.setattr(writer_mod, "_emit_json", flaky_emit_json)
        with pytest.raises(OSError, match="simulated disk full"):
            write_fixture(out, artifacts, scenario_bytes)
        assert not out.exists()
        leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".chaos-librarian-staging-")]
        assert leftover == []

    def test_sentinel_is_written_last(self, tmp_path: Path, monkeypatch) -> None:
        """If the rename fails, no sentinel must exist at ``out_dir``."""
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()

        def boom(self, target):
            raise OSError("boom")

        monkeypatch.setattr(writer_mod.Path, "replace", boom)
        with pytest.raises(OSError, match="boom"):
            write_fixture(out, artifacts, scenario_bytes)
        assert not out.exists()
