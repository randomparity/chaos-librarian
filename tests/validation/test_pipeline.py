"""Tests for run_validation orchestration and IssueCollector behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.scenario_io import LineIndex, ScenarioLoadError
from chaos_librarian.validation import codes, prepare_run_input, run_validation
from chaos_librarian.validation.pipeline import IssueCollector


def _write(tmp_path: Path, content: str, name: str = "scenario.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestPrepareRunInputLoaderErrors:
    """YAML parse failures and missing files surface as ScenarioLoadError.

    WHY: the byte-binding factory owns the parse step now. The CLI maps the
    exception to ``E_YAML_PARSE`` so callers still see a structured report;
    the contract that bad input never reaches ``run_validation`` is enforced
    by the factory raising rather than the pipeline emitting.
    """

    def test_yaml_syntax_error_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "key: [\n")
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(tmp_path / "missing.yaml")


class TestRunValidationTopLevelMappingGuard:
    """Non-mapping top-level YAML produces E_TOP_LEVEL_NOT_MAPPING (step 1.5).

    WHY: the shape pass assumes raw_data is a dict. A scalar (`42`) or
    sequence (`[]`) is valid YAML and not a YAMLError, so without this
    guard validate would crash. Closes Codex review finding #3.
    """

    def test_scalar_top_level_emits_code(self, tmp_path: Path) -> None:
        report = run_validation(prepare_run_input(_write(tmp_path, "42\n")))
        assert report.ok is False
        assert any(i.code == codes.E_TOP_LEVEL_NOT_MAPPING for i in report.issues)
        # exactly one issue — the pipeline returned early
        assert len(report.issues) == 1
        assert report.issues[0].line == 1
        assert report.issues[0].column == 0
        assert report.scenario_id == "<unknown>"

    def test_sequence_top_level_emits_code(self, tmp_path: Path) -> None:
        report = run_validation(prepare_run_input(_write(tmp_path, "- a\n- b\n")))
        assert report.ok is False
        assert any(i.code == codes.E_TOP_LEVEL_NOT_MAPPING for i in report.issues)
        assert len(report.issues) == 1

    def test_empty_file_emits_code(self, tmp_path: Path) -> None:
        """Empty YAML parses to None — not a mapping."""
        report = run_validation(prepare_run_input(_write(tmp_path, "")))
        assert report.ok is False
        assert any(i.code == codes.E_TOP_LEVEL_NOT_MAPPING for i in report.issues)


class TestRunValidationHappyPath:
    """A well-formed scenario passes both shape and semantic passes.

    WHY: this is the Sprint 1 exit-criteria smoke. If a valid fixture
    starts failing, the regression is in one of those passes.
    """

    def test_minimal_valid_scenario(self, tmp_path: Path) -> None:
        # Smallest valid Scenario: one work, one variant, one bundle, one asset,
        # no timeline events (all rules guard on emptiness and skip).
        path = _write(
            tmp_path,
            "schema_version: 5\n"
            "scenario_id: minimal\n"
            "seed: 1\n"
            "duration_scale: short\n"
            "library:\n"
            "  roots:\n"
            "    - id: r\n"
            "      path: r\n"
            "works:\n"
            "  - id: w\n"
            "    title: t\n"
            "    variants:\n"
            "      - id: v\n"
            "        label: l\n"
            "        bundle:\n"
            "          id: b\n"
            "          assets:\n"
            "            - id: a\n"
            "              role: primary_video\n"
            "              container: mkv\n"
            "              duration_seconds: 1\n"
            "timeline: []\n",
        )
        report = run_validation(prepare_run_input(path))
        assert report.ok is True
        assert report.issues == []
        assert report.scenario_id == "minimal"


class TestIssueCollectorLocResolution:
    """Loc tuples resolve to (line, column) via LineIndex, with walk-up fallback.

    WHY: if Pydantic returns a deep loc but only the parent has a line
    recorded (e.g., the field value is on a separate line), walking up
    keeps us from emitting (None, None) for an issue we know about.
    """

    def test_exact_hit(self) -> None:
        index = LineIndex(entries={("timeline", 3, "at"): (42, 14)})
        collector = IssueCollector()
        collector.add(
            code=codes.E_DURATION_SYNTAX,
            severity=ValidationSeverity.ERROR,
            message="bad",
            loc=("timeline", 3, "at"),
            line_index=index,
        )
        assert collector.issues[0].line == 42
        assert collector.issues[0].column == 14

    def test_walk_up_one_level(self) -> None:
        index = LineIndex(entries={("timeline", 3): (40, 4)})
        collector = IssueCollector()
        collector.add(
            code=codes.E_DURATION_SYNTAX,
            severity=ValidationSeverity.ERROR,
            message="bad",
            loc=("timeline", 3, "at"),
            line_index=index,
        )
        assert collector.issues[0].line == 40

    def test_whole_file_fallback(self) -> None:
        index = LineIndex()  # empty
        collector = IssueCollector()
        collector.add(
            code=codes.E_YAML_PARSE,
            severity=ValidationSeverity.ERROR,
            message="bad",
            loc=(),
            line_index=index,
        )
        assert collector.issues[0].line == 1
        assert collector.issues[0].column == 0


class TestRunValidationReportSorting:
    """Issues are sorted by (line, column, code) for stable output.

    WHY: deterministic ordering keeps diffs of report JSON small and
    makes golden-output tests possible downstream.
    """

    def test_sorted_by_position(self, tmp_path: Path) -> None:
        # A scenario with two field-level errors at different lines.
        path = _write(
            tmp_path,
            "schema_version: 5\n"
            "scenario_id: dup\n"
            "seed: 1\n"
            "duration_scale: short\n"
            "library:\n"
            "  roots: []\n"  # valid: empty roots
            "works: []\n"
            "timeline:\n"
            "  - id: e1\n"
            "    at: not-a-duration\n"  # E_DURATION_SYNTAX at line 10
            "    action: delete_file\n"
            "    target: nope\n"  # E_TARGET_UNKNOWN
            "  - id: e2\n"
            "    at: also-bad\n"  # E_DURATION_SYNTAX at line 14
            "    action: delete_file\n"
            "    target: nope2\n",
        )
        report = run_validation(prepare_run_input(path))
        lines = [i.line for i in report.issues if i.line is not None]
        assert lines == sorted(lines)
