"""Tests for chaos_librarian.validation.input."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import (
    RunInput,
    prepare_run_input,
    prepare_run_input_from_bytes,
)


class TestPrepareRunInput:
    """The factory binds raw bytes, hash, and parsed data in one record.

    WHY: validation, planning, and replay-bundle embedding must all describe
    the same byte sequence — otherwise ``validation.json`` can vouch for one
    payload while ``replay.json`` carries another. A single immutable read
    is the cheapest way to guarantee that.
    """

    def test_content_hash_matches_sha256_of_file(self, tmp_path: Path) -> None:
        path = tmp_path / "s.yaml"
        path.write_bytes(b"schema_version: 1\nscenario_id: s\nseed: 1\n")
        run_input = prepare_run_input(path)
        assert isinstance(run_input, RunInput)
        assert run_input.raw_bytes == path.read_bytes()
        assert run_input.content_hash == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_from_bytes_matches_from_path(self, tmp_path: Path) -> None:
        payload = b"schema_version: 1\nscenario_id: s\nseed: 1\n"
        path = tmp_path / "s.yaml"
        path.write_bytes(payload)
        a = prepare_run_input(path)
        b = prepare_run_input_from_bytes(raw_bytes=payload, source_label="memory:s")
        assert a.raw_data == b.raw_data
        assert a.content_hash == b.content_hash

    def test_yaml_parse_error_raises_from_factory(self, tmp_path: Path) -> None:
        """``ScenarioLoadError`` must surface from the factory, never inside
        ``run_validation`` — otherwise an upstream caller could skip the
        factory and bypass the byte-binding guarantee."""
        path = tmp_path / "broken.yaml"
        path.write_text("key: : value\n")  # invalid YAML
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(path)

    def test_missing_file_raises_from_factory(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(tmp_path / "missing.yaml")
