"""CLI tests for deterministic scenario generation."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FuzzLaneName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.scenario_io import parse_scenario_bytes

runner = CliRunner()


def _load_generated(path: Path) -> Scenario:
    raw, _ = parse_scenario_bytes(path.read_bytes(), source=path)
    return Scenario.model_validate(raw)


def test_generate_writes_valid_yaml_and_json_summary(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--seed",
            "123",
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["profile"] == "fuzz-smoke"
    assert payload["lane"] == FuzzLaneName.SMOKE.value
    assert payload["seed"] == 123
    assert payload["scenario_id"] == "fuzz-smoke-smoke-seed-123"
    assert payload["scenario_path"] == str(out.resolve())
    assert len(payload["sha256"]) == 64
    assert _load_generated(out).scenario_id == "fuzz-smoke-smoke-seed-123"


def test_generate_regression_requires_lane(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-regression", "--seed", "456", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert "--lane is required for fuzz-regression" in result.stdout + result.stderr
    assert not out.exists()


def test_generate_rejects_lane_profile_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--lane",
            "media-rewrite",
            "--seed",
            "123",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 2
    assert "lane media-rewrite is not valid for fuzz-smoke" in result.stdout + result.stderr
    assert not out.exists()


def test_generate_rejects_existing_out(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"
    out.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-smoke", "--seed", "123", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert out.read_text(encoding="utf-8") == "existing"


def test_generate_rejects_random_seed(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-smoke", "--seed", "random", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert not out.exists()
