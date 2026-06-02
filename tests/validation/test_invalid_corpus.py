"""Parametrized: every invalid fixture surfaces its expected code.

Each fixture's first line is ``# expected: E_<CODE>``. The test asserts
the report contains at least one issue with that code AND ``ok=False``.
A separate test asserts every valid fixture in tests/fixtures/scenarios/
produces ``ok=True`` with no issues (Sprint 1 exit-criteria smoke).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from chaos_librarian.validation import prepare_run_input, run_validation
from chaos_librarian.validation.scenario_io import ScenarioLoadError

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
INVALID_DIR = FIXTURE_DIR / "invalid"


_EXPECTED_RE = re.compile(r"#\s*expected:\s*(E_[A-Z_]+)")


def _expected_code(path: Path) -> str:
    first_line = path.read_text().splitlines()[0]
    m = _EXPECTED_RE.search(first_line)
    if m is None:
        raise AssertionError(
            f"{path.name}: first line must be `# expected: E_<CODE>`, got {first_line!r}"
        )
    return m.group(1)


def _invalid_fixtures() -> list[Path]:
    return sorted(INVALID_DIR.glob("*.yaml"))


def _valid_fixtures() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.yaml"))


@pytest.mark.parametrize("path", _invalid_fixtures(), ids=lambda p: p.name)
def test_invalid_fixture_produces_expected_code(path: Path) -> None:
    """Each invalid fixture surfaces at least one issue with its expected code.

    WHY: this is the regression guard for the public error-code set.
    Adding a code without a fixture (or removing a fixture without
    removing the code) is caught here.
    """
    expected = _expected_code(path)
    if expected == "E_YAML_PARSE":
        # The factory raises before validation runs; the CLI synthesizes the
        # report. Asserting the raise here is the equivalent regression guard.
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(path)
        return
    report = run_validation(prepare_run_input(path))
    assert report.ok is False, f"{path.name}: expected ok=False"
    assert any(i.code == expected for i in report.issues), (
        f"{path.name}: no issue with code {expected} in {[i.code for i in report.issues]}"
    )


@pytest.mark.parametrize("path", _valid_fixtures(), ids=lambda p: p.name)
def test_valid_fixture_validates_clean(path: Path) -> None:
    """Every top-level fixture is valid (Sprint 1 exit-criteria smoke).

    WHY: if a shipped fixture stops validating, either it has drifted
    from the schema or a new rule has a false positive. Either way the
    refactor that broke it must be reconsidered.
    """
    report = run_validation(prepare_run_input(path))
    assert report.ok is True, (
        f"{path.name}: expected ok=True, got issues {[i.code for i in report.issues]}"
    )
    assert report.issues == []
