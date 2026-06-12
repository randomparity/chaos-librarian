"""Invocation smoke + escaping checks for scripts/visualize_run.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "visualize_run.py"
TEMPLATE = Path(__file__).resolve().parents[2] / "scripts" / "visualize_template.html"
FIXTURE = "tests/fixtures/scenarios/active-library-churn.yaml"


def test_template_uses_textcontent_not_innerhtml() -> None:
    text = TEMPLATE.read_text()
    assert "innerHTML" not in text
    assert 'id="cl-payload"' in text


def _plan(tmp_path: Path) -> Path:
    out = tmp_path / "run"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "run", "chaos-librarian", "plan", FIXTURE, "--out", str(out)],
        check=True,
        capture_output=True,
    )
    return out


def test_script_writes_default_output(tmp_path: Path) -> None:
    run_dir = _plan(tmp_path)
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(run_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    html = run_dir / "visualize.html"
    assert html.exists()
    text = html.read_text()
    assert '<script type="application/json" id="cl-payload">' in text


def test_script_honors_output_flag(tmp_path: Path) -> None:
    run_dir = _plan(tmp_path)
    out = tmp_path / "custom.html"
    subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(run_dir), "-o", str(out)],
        check=True,
        capture_output=True,
    )
    assert out.exists()
    assert '<script type="application/json" id="cl-payload">' in out.read_text()


def test_missing_artifact_is_actionable_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(empty)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "replay.json" in result.stderr


def test_not_a_directory_is_actionable_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(missing)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "not a directory" in result.stderr
