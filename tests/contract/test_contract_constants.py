"""Lock the namespace UUID so accidental edits cause a test failure."""

from __future__ import annotations

import uuid

from chaos_librarian.contract import (
    ALBUM_REPORT_SCHEMA_VERSION,
    ARTIST_REPORT_SCHEMA_VERSION,
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    CAPABILITIES_SCHEMA_VERSION,
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    DISC_REPORT_SCHEMA_VERSION,
    DIVERGENCE_SCHEMA_VERSION,
    EPISODE_REPORT_SCHEMA_VERSION,
    JOURNAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    MOVIE_REPORT_SCHEMA_VERSION,
    OBSERVED_STATE_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    SEASON_REPORT_SCHEMA_VERSION,
    SERIES_REPORT_SCHEMA_VERSION,
    TRACK_REPORT_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract import scenario as scenario_contract
from chaos_librarian.contract.scenario import TimelineActionName


def test_namespace_uuid_is_stable() -> None:
    expected = uuid.uuid5(uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1")
    assert expected == CHAOS_LIBRARIAN_NAMESPACE_UUID


def test_namespace_uuid_is_v5() -> None:
    assert CHAOS_LIBRARIAN_NAMESPACE_UUID.version == 5


def test_current_contract_schema_versions() -> None:
    assert SCENARIO_SCHEMA_VERSION == 26
    assert MANIFEST_SCHEMA_VERSION == 9
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 12
    assert ASSET_REPORT_SCHEMA_VERSION == 9
    assert VARIANT_REPORT_SCHEMA_VERSION == 2
    assert OBSERVED_STATE_SCHEMA_VERSION == 4


def test_domain_report_schema_versions_start_at_one() -> None:
    assert MOVIE_REPORT_SCHEMA_VERSION == 1
    assert SERIES_REPORT_SCHEMA_VERSION == 1
    assert SEASON_REPORT_SCHEMA_VERSION == 1
    assert EPISODE_REPORT_SCHEMA_VERSION == 1
    assert ARTIST_REPORT_SCHEMA_VERSION == 1
    assert ALBUM_REPORT_SCHEMA_VERSION == 1
    assert DISC_REPORT_SCHEMA_VERSION == 1
    assert TRACK_REPORT_SCHEMA_VERSION == 1


def test_materialization_schema_version_bumped_to_15() -> None:
    assert MATERIALIZATION_SCHEMA_VERSION == 15


def test_capabilities_schema_version_bumped_to_7() -> None:
    assert CAPABILITIES_SCHEMA_VERSION == 7


def test_issue_138_schema_versions() -> None:
    assert SCENARIO_SCHEMA_VERSION == 26
    assert MATERIALIZATION_SCHEMA_VERSION == 15
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 12
    assert CAPABILITIES_SCHEMA_VERSION == 7


def test_issue_139_schema_versions() -> None:
    assert SCENARIO_SCHEMA_VERSION == 26
    assert MATERIALIZATION_SCHEMA_VERSION == 15
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 12
    assert CAPABILITIES_SCHEMA_VERSION == 7


def test_all_schema_versions_are_positive_integers() -> None:
    versions = [
        ALBUM_REPORT_SCHEMA_VERSION,
        ARTIST_REPORT_SCHEMA_VERSION,
        ASSET_REPORT_SCHEMA_VERSION,
        BUNDLE_REPORT_SCHEMA_VERSION,
        CAPABILITIES_SCHEMA_VERSION,
        DISC_REPORT_SCHEMA_VERSION,
        DIVERGENCE_SCHEMA_VERSION,
        EPISODE_REPORT_SCHEMA_VERSION,
        JOURNAL_SCHEMA_VERSION,
        MANIFEST_SCHEMA_VERSION,
        MATERIALIZATION_SCHEMA_VERSION,
        MOVIE_REPORT_SCHEMA_VERSION,
        OBSERVED_STATE_SCHEMA_VERSION,
        REPLAY_BUNDLE_SCHEMA_VERSION,
        RUN_SENTINEL_SCHEMA_VERSION,
        SCENARIO_SCHEMA_VERSION,
        SEASON_REPORT_SCHEMA_VERSION,
        SERIES_REPORT_SCHEMA_VERSION,
        TRACK_REPORT_SCHEMA_VERSION,
        VALIDATION_SCHEMA_VERSION,
        VARIANT_REPORT_SCHEMA_VERSION,
    ]
    assert all(isinstance(v, int) and v >= 1 for v in versions)


def test_adapter_schema_versions() -> None:
    assert OBSERVED_STATE_SCHEMA_VERSION == 4
    assert DIVERGENCE_SCHEMA_VERSION == 1


def test_hierarchy_timeline_actions_are_contract_owned() -> None:
    assert hasattr(scenario_contract, "HIERARCHY_TIMELINE_ACTIONS")
    assert (
        frozenset(
            {
                TimelineActionName.RENUMBER_EPISODE,
                TimelineActionName.MOVE_EPISODE_TO_SEASON,
                TimelineActionName.RENAME_SEASON,
                TimelineActionName.RENUMBER_DISC,
                TimelineActionName.MOVE_TRACK_TO_DISC,
            }
        )
        == scenario_contract.HIERARCHY_TIMELINE_ACTIONS
    )
