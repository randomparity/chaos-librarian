"""End-to-end tests for the inspect CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path, steps: int | None) -> Path:
    out = tmp_path / "run"
    args = ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)]
    if steps is not None:
        args += ["--steps", str(steps)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


class TestInspect:
    """inspect emits a JSON summary or a human block.

    WHY: agents pipe --json output through jq; humans want a clean block.
    """

    def test_full_fixture_json(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=None)
        result = runner.invoke(app, ["inspect", str(fixture), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["execution_mode"] == "plan_only"
        assert payload["journal_entries"] == 2
        assert payload["steps_remaining"] == 0
        assert payload["counts"]["assets"] == 1

    def test_partial_fixture_steps_remaining(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=1)
        result = runner.invoke(app, ["inspect", str(fixture), "--json"])
        payload = json.loads(result.stdout)
        assert payload["steps_remaining"] == 1
        assert payload["journal_entries"] == 1

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=None)
        (fixture / ".chaos-librarian-run").unlink()
        result = runner.invoke(app, ["inspect", str(fixture)])
        assert result.exit_code == 7

    def test_inspect_slow_copy_partial(self, tmp_path: Path) -> None:
        """inspect reports step-unit counts, not raw event counts.

        WHY: Codex round 3 finding 1 — --next is step-unit-counted; the
        inspect summary must use the same unit so adapters see a
        consistent story.
        """
        out = tmp_path / "run"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--steps", "0"],
        )
        result = runner.invoke(app, ["inspect", str(out), "--json"])
        payload = json.loads(result.stdout)
        assert payload["applied_steps"] == 0
        assert payload["steps_remaining"] == 1  # one step unit covers the whole pair
        assert payload["applied_events"] == 0
        assert payload["journal_entries"] == 0
