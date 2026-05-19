"""End-to-end tests for the clean CLI command."""

from __future__ import annotations

import json
import shutil
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


class TestCleanFixtureInconsistent:
    """clean refuses directories where the sentinel doesn't match the bundle.

    WHY: Codex round 4 finding 2. The previous gate authorized
    shutil.rmtree on any directory whose .chaos-librarian-run parsed.
    A stale or copied sentinel into an unrelated directory was enough
    to delete user data recursively. clean now requires replay.json
    to exist, parse, and carry the same run_id as the sentinel.
    """

    def test_copied_sentinel_to_unrelated_dir_refused(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        bare = tmp_path / "user-data"
        bare.mkdir()
        (bare / "important.txt").write_text("don't delete me")
        shutil.copy(fixture / ".chaos-librarian-run", bare / ".chaos-librarian-run")
        result = runner.invoke(app, ["clean", str(bare)])
        assert result.exit_code == 7
        assert bare.exists()
        assert (bare / "important.txt").read_text() == "don't delete me"

    def test_mismatched_run_id_refused(self, tmp_path: Path) -> None:
        """Sentinel from fixture A spliced over fixture B's sentinel → exit 7."""
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        out_a = tmp_path / "a" / "run"
        out_b = tmp_path / "b" / "run"
        assert (
            runner.invoke(
                app,
                ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out_a)],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                app,
                ["plan", str(FIXTURE_DIR / "version-evolution.yaml"), "--out", str(out_b)],
            ).exit_code
            == 0
        )
        shutil.copy(out_a / ".chaos-librarian-run", out_b / ".chaos-librarian-run")
        result = runner.invoke(app, ["clean", str(out_b)])
        assert result.exit_code == 7
        assert out_b.exists()

    def test_missing_replay_json_refused(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        (fixture / "replay.json").unlink()
        result = runner.invoke(app, ["clean", str(fixture)])
        assert result.exit_code == 7
        assert fixture.exists()

    def test_json_error_payload(self, tmp_path: Path) -> None:
        """--json failure payload distinguishes fixture_inconsistent from sentinel_invalid."""
        fixture = _make_fixture(tmp_path)
        bare = tmp_path / "user-data"
        bare.mkdir()
        shutil.copy(fixture / ".chaos-librarian-run", bare / ".chaos-librarian-run")
        result = runner.invoke(app, ["clean", str(bare), "--json"])
        assert result.exit_code == 7
        payload = json.loads(result.stderr)
        assert payload["error"] == "fixture_inconsistent"
