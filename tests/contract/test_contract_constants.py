"""Lock the namespace UUID so accidental edits cause a test failure."""

from __future__ import annotations

import uuid

from chaos_librarian.contract import (
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    JOURNAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
)


def test_namespace_uuid_is_stable() -> None:
    expected = uuid.uuid5(uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1")
    assert expected == CHAOS_LIBRARIAN_NAMESPACE_UUID


def test_namespace_uuid_is_v5() -> None:
    assert CHAOS_LIBRARIAN_NAMESPACE_UUID.version == 5


def test_all_schema_versions_are_positive_integers() -> None:
    versions = [
        SCENARIO_SCHEMA_VERSION,
        MANIFEST_SCHEMA_VERSION,
        JOURNAL_SCHEMA_VERSION,
        REPLAY_BUNDLE_SCHEMA_VERSION,
        VALIDATION_SCHEMA_VERSION,
        MATERIALIZATION_SCHEMA_VERSION,
        RUN_SENTINEL_SCHEMA_VERSION,
    ]
    assert all(isinstance(v, int) and v >= 1 for v in versions)
