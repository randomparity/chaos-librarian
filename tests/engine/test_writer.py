"""Tests for chaos_librarian.engine.writer."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION, REPLAY_BUNDLE_SCHEMA_VERSION
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
from chaos_librarian.contract.reports import AssetReport
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import PlanArtifacts, run_plan, step_fixture
from chaos_librarian.engine import writer as writer_mod
from chaos_librarian.engine.reports import ReportSet
from chaos_librarian.engine.writer import append_step, write_fixture
from chaos_librarian.validation import RunInput, prepare_run_input_from_bytes

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")

_REPORT_DIRS = [
    "assets",
    "movies",
    "series",
    "seasons",
    "episodes",
    "artists",
    "albums",
    "discs",
    "tracks",
    "variants",
    "bundles",
]

_IDENTITY_MOVE_RENAME = b"""\
schema_version: 14
scenario_id: identity-move-rename
seed: 42
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd
    - id: movies_4k
      path: movies-4k

movies:
  - id: movie_blazar
    title: Synthetic Blazar
    layout: movie_flat
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_hd_main
              role: primary_video
              container: mkv
              duration_seconds: 12
              video:
                source: mandelbrot
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []

timeline:
  - id: move_001
    at: 2s
    action: move_asset
    target: asset_hd_main
    to: movies-hd/Synthetic Blazar (HD).mkv
  - id: rename_001
    at: 4s
    action: rename_file
    target: asset_hd_main
    to: movies-hd/Blazar.mkv
"""

_ACTIVE_LIBRARY_CHURN = b"""\
schema_version: 14
scenario_id: active-library-churn
seed: 17
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd

movies:
  - id: movie_pulsar
    title: Synthetic Pulsar
    layout: movie_flat
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []

timeline:
  - id: move_001
    at: 1ns
    action: move_asset
    target: asset_main
    to: movies-hd/Pulsar.mkv
  - id: copy_start_001
    at: 2ns
    action: slow_copy_start
    target: asset_main
    to: movies-hd/Pulsar Copy.mkv
    temp_path: movies-hd/Pulsar Copy.mkv.part
    duration: 4ns
  - id: copy_commit_001
    at: 6ns
    action: slow_copy_commit
    for: copy_start_001
  - id: sidecar_create_001
    at: 7ns
    action: create_sidecar
    target: asset_main
    to: movies-hd/Pulsar.nfo
    kind: nfo
  - id: sidecar_update_001
    at: 8ns
    action: update_sidecar
    target: asset_main
    sidecar_path: movies-hd/Pulsar.nfo
  - id: metadata_001
    at: 9ns
    action: edit_metadata
    target: asset_main
    fields:
      title: Synthetic Pulsar Updated
  - id: delete_001
    at: 10ns
    action: delete_file
    target: asset_main
  - id: add_001
    at: 11ns
    action: add_file
    target: asset_main
    to: movies-hd/Pulsar Restored.mkv
"""


def _prepare(raw_bytes: bytes) -> tuple[RunInput, ValidationReport]:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=raw_bytes,
        source_label="test:engine-writer",
    )
    return run_input, _validation_report(run_input.scenario.scenario_id)


def _validation_report(scenario_id: str) -> ValidationReport:
    return ValidationReport(schema_version=1, scenario_id=scenario_id, ok=True, issues=[])


def _empty_report_set() -> ReportSet:
    return ReportSet(
        assets=(),
        movies=(),
        series=(),
        seasons=(),
        episodes=(),
        artists=(),
        albums=(),
        discs=(),
        tracks=(),
        variants=(),
        bundles=(),
    )


def _empty_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )


def _empty_artifacts() -> tuple[PlanArtifacts, bytes]:
    empty_manifest = _empty_manifest()
    bundle = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="schema_version: 14\n",
        run_id=_RUN_ID,
        resolved_seed=1,
        applied_events=0,
        journal_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        execution_trace=[],
        execution_mode=ExecutionMode.PLAN_ONLY,
    )
    sentinel = RunSentinel(
        run_id=_RUN_ID,
        schema_version=2,
        created_by="chaos-librarian 0.0.0",
        created_at=None,
    )
    artifacts = PlanArtifacts(
        initial_manifest=empty_manifest,
        current_manifest=empty_manifest,
        journal=(),
        replay_bundle=bundle,
        validation_report=_validation_report("t"),
        sentinel=sentinel,
        reports=_empty_report_set(),
    )
    return artifacts, b"schema_version: 14\n"


class TestWriteFixtureFileSet:
    """write_fixture writes the contracted artifacts at the run directory.

    WHY: any extra entry becomes part of the contract; any missing entry
    breaks the fixture-layout doc. The set plus the ``reports/`` tree is
    the contract.
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
        assert text == ""


class TestWriteFixtureRefusesExistingDir:
    """write_fixture refuses a pre-existing target directory.

    WHY: ``--out`` callback also refuses; this is defense in depth. A
    scenario where the callback is bypassed still must not clobber.
    """

    def test_existing_dir_raises(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        out.mkdir()
        artifacts, scenario_bytes = _empty_artifacts()

        with pytest.raises(FileExistsError):
            write_fixture(out, artifacts, scenario_bytes)


class TestWriteFixtureDeterministicBytes:
    """Two writes of the same artifacts produce byte-identical files."""

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
    """The plan-only replay bundle on disk omits ``created_at``."""

    def test_replay_json_has_no_created_at(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()

        write_fixture(out, artifacts, scenario_bytes)

        payload = json.loads((out / "replay.json").read_text())
        assert "created_at" not in payload
        assert "toolchain" not in payload


class TestWriteFixtureIsTransactional:
    """A mid-write failure leaves no fixture at all."""

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
    rely on them. The domain subdir layout is public contract.
    """

    def test_reports_subdirs_exist(self, tmp_path: Path) -> None:
        run_input, report = _prepare(_IDENTITY_MOVE_RENAME)
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"

        write_fixture(out, artifacts, run_input.raw_bytes)

        for report_dir in _REPORT_DIRS:
            assert (out / "reports" / report_dir).is_dir()
        assert not (out / "reports" / "works").exists()

    def test_asset_report_file_per_id(self, tmp_path: Path) -> None:
        run_input, report = _prepare(_IDENTITY_MOVE_RENAME)
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"

        write_fixture(out, artifacts, run_input.raw_bytes)

        assert (out / "reports" / "assets" / "asset_hd_main.json").exists()

    def test_domain_report_file_per_id(self, tmp_path: Path) -> None:
        run_input, report = _prepare(_IDENTITY_MOVE_RENAME)
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"

        write_fixture(out, artifacts, run_input.raw_bytes)

        assert (out / "reports" / "movies" / "movie_blazar.json").exists()
        assert (out / "reports" / "variants" / "variant_hd.json").exists()
        assert (out / "reports" / "bundles" / "bundle_hd.json").exists()

    def test_two_writes_byte_identical(self, tmp_path: Path) -> None:
        run_input, report = _prepare(_IDENTITY_MOVE_RENAME)
        artifacts = run_plan(run_input=run_input, validation_report=report)
        a = tmp_path / "a"
        b = tmp_path / "b"

        write_fixture(a, artifacts, run_input.raw_bytes)
        write_fixture(b, artifacts, run_input.raw_bytes)

        for report_dir in _REPORT_DIRS:
            a_files = sorted((a / "reports" / report_dir).iterdir())
            b_files = sorted((b / "reports" / report_dir).iterdir())
            assert [p.name for p in a_files] == [p.name for p in b_files]
            for fa, fb in zip(a_files, b_files, strict=True):
                assert fa.read_bytes() == fb.read_bytes(), fa.name


class TestAppendStep:
    """append_step updates manifest.current/replay.json/reports atomically."""

    def test_journal_grows(self, tmp_path: Path) -> None:
        run_input, report = _prepare(_IDENTITY_MOVE_RENAME)
        artifacts = run_plan(
            run_input=run_input,
            validation_report=report,
            steps_limit=0,
        )
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        assert (out / "journal.jsonl").read_text() == ""

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

        assert sum(1 for _ in (out / "journal.jsonl").read_text().splitlines()) == 1

    def test_deleted_asset_report_keeps_required_current_null(self, tmp_path: Path) -> None:
        run_input, report = _prepare(_ACTIVE_LIBRARY_CHURN)
        artifacts = run_plan(
            run_input=run_input,
            validation_report=report,
            steps_limit=3,
        )
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)

        step_result = step_fixture(out, n_steps=3)
        append_step(
            out,
            new_entries=step_result.new_entries,
            new_current_manifest=step_result.new_current_manifest,
            new_report_set=step_result.new_report_set,
            new_replay_bundle=step_result.new_replay_bundle,
        )

        report_path = out / "reports" / "assets" / "asset_main.json"
        report_json = report_path.read_text()
        payload = json.loads(report_json)
        assert "current" in payload
        assert payload["current"] is None
        AssetReport.model_validate_json(report_json)
