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
from chaos_librarian.engine import PlanArtifacts, run_plan
from chaos_librarian.engine import writer as writer_mod
from chaos_librarian.engine.reports import ReportSet
from chaos_librarian.engine.writer import append_step, write_fixture
from chaos_librarian.validation import RunInput, prepare_run_input, run_validation

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _prepare(scenario_name: str) -> tuple[RunInput, ValidationReport]:
    run_input = prepare_run_input(FIXTURE_DIR / scenario_name)
    return run_input, run_validation(run_input)


def _empty_artifacts() -> tuple[PlanArtifacts, bytes]:
    empty_manifest = Manifest(
        schema_version=2,
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
        reports=ReportSet(assets=(), works=(), variants=(), bundles=()),
    )
    return artifacts, b"schema_version: 1\n"


class TestWriteFixtureFileSet:
    """write_fixture writes the contracted artifacts at the run directory.

    WHY: any extra entry becomes part of the contract; any missing entry
    breaks the fixture-layout doc. The set (seven files plus the
    ``reports/`` tree added in Sprint 4) is the contract.
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
            "reports",
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


class TestWriterEmitsReports:
    """write_fixture stages reports/ subdirs before the atomic rename.

    WHY: reports are part of every plan-only fixture; adapter consumers
    rely on them. The subdir layout (assets/works/variants/bundles) is
    public contract.
    """

    def test_reports_subdirs_exist(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        assert (out / "reports" / "assets").is_dir()
        assert (out / "reports" / "works").is_dir()
        assert (out / "reports" / "variants").is_dir()
        assert (out / "reports" / "bundles").is_dir()

    def test_asset_report_file_per_id(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        assert (out / "reports" / "assets" / "asset_hd_main.json").exists()

    def test_two_writes_byte_identical(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        a = tmp_path / "a"
        b = tmp_path / "b"
        write_fixture(a, artifacts, run_input.raw_bytes)
        write_fixture(b, artifacts, run_input.raw_bytes)
        for report_dir in ["assets", "works", "variants", "bundles"]:
            a_files = sorted((a / "reports" / report_dir).iterdir())
            b_files = sorted((b / "reports" / report_dir).iterdir())
            assert [p.name for p in a_files] == [p.name for p in b_files]
            for fa, fb in zip(a_files, b_files, strict=True):
                assert fa.read_bytes() == fb.read_bytes(), fa.name


class TestAppendStep:
    """append_step updates manifest.current/replay.json/reports atomically.

    WHY: step mode mutates a fixture in-place; the updated files must
    appear consistently or not at all.
    """

    def test_journal_grows(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(
            run_input=run_input,
            validation_report=report,
            steps_limit=0,
        )
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        # Journal starts empty
        assert (out / "journal.jsonl").read_text() == ""
        # Re-plan with the first event applied
        artifacts_after = run_plan(
            run_input=run_input,
            validation_report=report,
            steps_limit=1,
        )
        new_entries = artifacts_after.journal
        append_step(
            out,
            new_entries=new_entries,
            new_current_manifest=artifacts_after.current_manifest,
            new_report_set=artifacts_after.reports,
            new_replay_bundle=artifacts_after.replay_bundle,
        )
        # One line now present in the journal
        assert sum(1 for _ in (out / "journal.jsonl").read_text().splitlines()) == 1
