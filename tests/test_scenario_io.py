"""Tests for chaos_librarian.scenario_io: YAML loader + LineIndex."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chaos_librarian.scenario_io import ScenarioLoadError, load_scenario


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(content)
    return path


class TestLoadScenarioHappyPath:
    """Valid YAML returns a plain dict and a line-index keyed by path tuple.

    WHY: downstream validation passes must work with plain Python types and
    must be able to resolve any field back to its (line, column) for the
    final ValidationReport.
    """

    def test_returns_plain_dict_and_line_index(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            ("schema_version: 1\nscenario_id: t\ntimeline:\n  - id: e1\n    at: 1s\n"),
        )
        raw, index, raw_bytes, content_hash = load_scenario(path)
        assert isinstance(raw, dict)
        assert raw["scenario_id"] == "t"
        assert isinstance(raw["timeline"], list)
        assert raw["timeline"][0]["id"] == "e1"
        # Downstream code should see no ruamel types anywhere.
        assert type(raw).__name__ == "dict"
        assert type(raw["timeline"]).__name__ == "list"
        # Top-level keys are at known 1-based lines.
        assert index.lookup(("schema_version",)) == (1, 0)
        assert index.lookup(("scenario_id",)) == (2, 0)
        assert index.lookup(("timeline",)) == (3, 0)
        # Nested keys carry their own positions.
        assert index.lookup(("timeline", 0, "id")) == (4, 4)
        assert index.lookup(("timeline", 0, "at")) == (5, 4)
        # Bytes preserved verbatim; hash is sha256 of those exact bytes.
        assert raw_bytes == path.read_bytes()
        assert content_hash == hashlib.sha256(raw_bytes).hexdigest()

    def test_missing_path_lookup_returns_none(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "scenario_id: t\n")
        _, index, _, _ = load_scenario(path)
        assert index.lookup(("nonexistent",)) is None
        assert index.lookup(("timeline", 99, "at")) is None


class TestLoadScenarioErrors:
    """YAML syntax errors are surfaced as ScenarioLoadError with line/col.

    WHY: the pipeline emits a single E_YAML_PARSE issue carrying the
    reported position; validate cannot proceed without parsed YAML.
    """

    def test_yaml_syntax_error_raises_load_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "key: : value\n")  # double-colon trips ruamel
        with pytest.raises(ScenarioLoadError) as excinfo:
            load_scenario(path)
        assert excinfo.value.line is not None
        assert excinfo.value.line >= 1

    def test_missing_file_raises_load_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        with pytest.raises(ScenarioLoadError):
            load_scenario(missing)


class TestLineIndexTopLevelShape:
    """Non-mapping top-level YAML returns a non-dict raw value.

    WHY: the pipeline's step 1.5 (top-level mapping guard) needs to detect
    scalars and sequences and short-circuit before the shape pass crashes.
    """

    def test_scalar_top_level(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")
        raw, _, _, _ = load_scenario(path)
        assert raw == 42

    def test_sequence_top_level(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "- a\n- b\n")
        raw, _, _, _ = load_scenario(path)
        assert raw == ["a", "b"]
