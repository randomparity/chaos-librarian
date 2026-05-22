"""CLI tests for the Sprint 9 compare command."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.adapter.fixture import load_fixture
from chaos_librarian.cli.app import app
from chaos_librarian.contract.observed_state import ObservedState
from tests.support.adapter import observed_from_fixture as _observed_from_fixture
from tests.support.adapter import write_plan_fixture as _write_plan_fixture

runner = CliRunner()


def _write_observed(path: Path, observed: ObservedState) -> None:
    path.write_text(observed.model_dump_json(indent=2, exclude_none=True))


def test_compare_help_succeeds() -> None:
    result = runner.invoke(app, ["compare", "--help"])

    assert result.exit_code == 0


def test_compare_clean_exits_zero_and_writes_json_report(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path, "static-library.yaml")
    fixture = load_fixture(run_dir)
    observed_path = tmp_path / "observed.json"
    _write_observed(observed_path, _observed_from_fixture(fixture))

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path), "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True


def test_compare_divergent_exits_six_and_writes_json_report(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path, "static-library.yaml")
    fixture = load_fixture(run_dir)
    observed_path = tmp_path / "observed.json"
    _write_observed(
        observed_path,
        _observed_from_fixture(fixture, path_override="library/Different.mkv"),
    )

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path), "--json"])

    payload = json.loads(result.stdout)
    assert result.exit_code == 6
    assert payload["ok"] is False
    assert payload["findings"]


def test_compare_identity_history_missing_evidence_exits_six(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path, "identity-move-rename.yaml")
    fixture = load_fixture(run_dir)
    observed_path = tmp_path / "observed.json"
    _write_observed(observed_path, _observed_from_fixture(fixture))

    result = runner.invoke(
        app,
        ["compare", str(run_dir), str(observed_path), "--mode", "identity-history", "--json"],
    )

    assert result.exit_code == 6
    finding_codes = {finding["code"] for finding in json.loads(result.stdout)["findings"]}
    assert "D_HISTORY_MISSING" in finding_codes


def test_compare_malformed_observed_json_exits_one_with_error_envelope(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path, "static-library.yaml")
    observed_path = tmp_path / "observed.json"
    observed_path.write_text("{")

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.stderr)["error_code"] == "E_ADAPTER_OBSERVED_INVALID"


def test_compare_run_id_mismatch_exits_one_not_divergence(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path, "static-library.yaml")
    fixture = load_fixture(run_dir)
    observed_path = tmp_path / "observed.json"
    _write_observed(observed_path, _observed_from_fixture(fixture, run_id=uuid.uuid4()))

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path), "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["error_code"] == "E_ADAPTER_RUN_ID_MISMATCH"


def test_compare_missing_sentinel_exits_seven(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path, "static-library.yaml")
    fixture = load_fixture(run_dir)
    observed_path = tmp_path / "observed.json"
    _write_observed(observed_path, _observed_from_fixture(fixture))
    (run_dir / ".chaos-librarian-run").unlink()

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path), "--json"])

    assert result.exit_code == 7
    assert json.loads(result.stderr)["error_code"] == "E_SENTINEL_INVALID"


def test_compare_rejects_missing_run_dir(tmp_path: Path) -> None:
    observed_path = tmp_path / "observed.json"
    observed_path.write_text("{}")

    result = runner.invoke(app, ["compare", str(tmp_path / "missing"), str(observed_path)])

    assert result.exit_code == 2


def test_compare_rejects_file_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "not-a-dir"
    run_dir.write_text("")
    observed_path = tmp_path / "observed.json"
    observed_path.write_text("{}")

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path)])

    assert result.exit_code == 2


def test_compare_rejects_missing_observed_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = runner.invoke(app, ["compare", str(run_dir), str(tmp_path / "missing.json")])

    assert result.exit_code == 2


def test_compare_rejects_observed_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    observed_path = tmp_path / "observed"
    observed_path.mkdir()

    result = runner.invoke(app, ["compare", str(run_dir), str(observed_path)])

    assert result.exit_code == 2
