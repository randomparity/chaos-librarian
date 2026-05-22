"""Tests for loading consumer observed-state JSON."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.adapter.errors import E_ADAPTER_OBSERVED_INVALID, AdapterInputError
from chaos_librarian.adapter.observed import load_observed_state


def _observed_payload() -> str:
    return """
{
  "schema_version": 1,
  "consumer": {"name": "voom-v2", "version": "0.9.0"},
  "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
  "observed_at": "2026-05-22T12:00:00Z",
  "assets": [
    {
      "observed_ref": "obs-asset-1",
      "current_path": "movies/Synthetic.mkv"
    }
  ]
}
""".strip()


def _assert_observed_invalid(path: Path) -> None:
    with pytest.raises(AdapterInputError) as exc_info:
        load_observed_state(path)
    assert exc_info.value.error_code == E_ADAPTER_OBSERVED_INVALID


def test_load_observed_state_reads_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "observed-state.json"
    path.write_text(_observed_payload())

    observed = load_observed_state(path)

    assert observed.consumer.name == "voom-v2"
    assert observed.assets[0].observed_ref == "obs-asset-1"


def test_load_observed_state_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "observed-state.json"
    path.write_text("{")

    _assert_observed_invalid(path)


def test_load_observed_state_rejects_schema_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "observed-state.json"
    path.write_text('{"schema_version": 1, "assets": []}')

    _assert_observed_invalid(path)
