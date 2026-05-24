"""Verify committed JSON Schemas match current Pydantic models.

This duplicates the CI gate (`python -m chaos_librarian.schema_export --check`)
so editors that forget to regenerate get a fast local signal from pytest.
"""

from __future__ import annotations

import json
from pathlib import Path

from chaos_librarian.schema_export import MODELS, check_all


def test_committed_schemas_match_models() -> None:
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    drift = check_all(schemas_dir)
    assert drift == [], (
        f"Stale schemas: {drift}. Regenerate with: python -m chaos_librarian.schema_export --write"
    )


def test_all_schemas_listed() -> None:
    names = {filename for filename, _ in MODELS}
    assert names == {
        "asset-report.schema.json",
        "bundle-report.schema.json",
        "capabilities.schema.json",
        "divergence.schema.json",
        "journal.schema.json",
        "manifest.schema.json",
        "materialization.schema.json",
        "observed-state.schema.json",
        "replay-bundle.schema.json",
        "run-sentinel.schema.json",
        "scenario.schema.json",
        "validation.schema.json",
        "variant-report.schema.json",
        "work-report.schema.json",
    }
    assert "profiles.schema.json" not in names


def test_journal_schema_has_oneof_on_phase() -> None:
    # Discriminated unions emit either top-level oneOf or under $defs;
    # either way, the discriminator key must appear so external consumers
    # can statically distinguish atomic/started/progressed/committed/aborted.
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    journal_schema = json.loads((schemas_dir / "journal.schema.json").read_text())
    assert "discriminator" in journal_schema or "oneOf" in journal_schema


def test_replay_bundle_schema_has_oneof_on_execution_mode() -> None:
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    bundle_schema = json.loads((schemas_dir / "replay-bundle.schema.json").read_text())
    assert "discriminator" in bundle_schema or "oneOf" in bundle_schema


def test_scenario_schema_freezes_generation_profile_version() -> None:
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    scenario_schema = json.loads((schemas_dir / "scenario.schema.json").read_text())
    profile_version = scenario_schema["$defs"]["ScenarioGeneration"]["properties"][
        "profile_version"
    ]

    assert profile_version["const"] == 1
    assert "minimum" not in profile_version
