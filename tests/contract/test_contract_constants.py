"""Lock the namespace UUID so accidental edits cause a test failure."""

from __future__ import annotations

import uuid

from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    CAPABILITIES_SCHEMA_VERSION,
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    JOURNAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
    WORK_REPORT_SCHEMA_VERSION,
)


def test_namespace_uuid_is_stable() -> None:
    expected = uuid.uuid5(uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1")
    assert expected == CHAOS_LIBRARIAN_NAMESPACE_UUID


def test_namespace_uuid_is_v5() -> None:
    assert CHAOS_LIBRARIAN_NAMESPACE_UUID.version == 5


def test_scenario_schema_version_bumped_to_6():
    assert SCENARIO_SCHEMA_VERSION == 6


def test_manifest_schema_version_bumped_to_4():
    assert MANIFEST_SCHEMA_VERSION == 4


def test_replay_bundle_schema_version_bumped_to_5() -> None:
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 5


def test_asset_report_schema_version_bumped_to_4():
    assert ASSET_REPORT_SCHEMA_VERSION == 4


def test_materialization_schema_version_bumped_to_5():
    assert MATERIALIZATION_SCHEMA_VERSION == 5


def test_all_schema_versions_are_positive_integers() -> None:
    versions = [
        ASSET_REPORT_SCHEMA_VERSION,
        BUNDLE_REPORT_SCHEMA_VERSION,
        CAPABILITIES_SCHEMA_VERSION,
        JOURNAL_SCHEMA_VERSION,
        MANIFEST_SCHEMA_VERSION,
        MATERIALIZATION_SCHEMA_VERSION,
        REPLAY_BUNDLE_SCHEMA_VERSION,
        RUN_SENTINEL_SCHEMA_VERSION,
        SCENARIO_SCHEMA_VERSION,
        VALIDATION_SCHEMA_VERSION,
        VARIANT_REPORT_SCHEMA_VERSION,
        WORK_REPORT_SCHEMA_VERSION,
    ]
    assert all(isinstance(v, int) and v >= 1 for v in versions)
