"""End-to-end tests for the clean CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path) -> Path:
    out = tmp_path / "run"
    result = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)]
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


class TestClean:
    """clean removes sentinel'd directories, refuses everything else.

    WHY: V1's only protection against rm-rf-by-mistake is the sentinel.
    """

    def test_removes_sentinel_dir(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = runner.invoke(app, ["clean", str(fixture)])
        assert result.exit_code == 0
        assert not fixture.exists()

    def test_json_output(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        resolved = str(fixture.resolve())
        result = runner.invoke(app, ["clean", str(fixture), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["removed"] == resolved
        assert "run_id" in payload

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / "data.txt").write_text("important")
        result = runner.invoke(app, ["clean", str(bare)])
        assert result.exit_code == 7
        assert bare.exists()
        assert (bare / "data.txt").exists()

    def test_malformed_sentinel(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / ".chaos-librarian-run").write_text("not json")
        result = runner.invoke(app, ["clean", str(bad)])
        assert result.exit_code == 7
        assert bad.exists()
