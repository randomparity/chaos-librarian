"""End-to-end tests for the validate CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _write(tmp_path: Path, content: str, name: str = "s.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestValidateExitCodes:
    """Valid scenarios exit 0; any error-severity issue exits 3.

    WHY: the exit code is the contract surface for CI gates and agentic
    scripting. JSON output is also stable; humans get a separate format.
    """

    def test_valid_fixture_exits_zero(self) -> None:
        result = runner.invoke(app, ["validate", str(FIXTURE_DIR / "identity-move-rename.yaml")])
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_invalid_scenario_exits_three(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")  # top-level scalar → E_TOP_LEVEL_NOT_MAPPING
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code == 3


class TestValidateJSONShape:
    """``--json`` emits a ValidationReport-shaped JSON object.

    WHY: voom-v2 and agentic tooling consume this output; the shape is
    frozen by ``schemas/validation.schema.json``.
    """

    def test_json_for_valid_scenario(self) -> None:
        result = runner.invoke(
            app, ["validate", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["issues"] == []

    def test_json_for_invalid_scenario(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")
        result = runner.invoke(app, ["validate", str(path), "--json"])
        assert result.exit_code == 3
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert any(i["code"] == "E_TOP_LEVEL_NOT_MAPPING" for i in payload["issues"])


class TestValidateHumanOutput:
    """Default (no ``--json``) emits a human-readable report.

    WHY: this is the interactive format; format may change but presence
    of basic columns (status, code, message) should not.
    """

    def test_human_for_valid_scenario(self) -> None:
        result = runner.invoke(app, ["validate", str(FIXTURE_DIR / "identity-move-rename.yaml")])
        assert result.exit_code == 0
        assert "identity-move-rename" in result.stdout
        assert "OK" in result.stdout

    def test_human_for_invalid_scenario(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code == 3
        assert "FAIL" in result.stdout
        assert "E_TOP_LEVEL_NOT_MAPPING" in result.stdout
