"""Tests for identity-history adapter comparison."""

from __future__ import annotations

from dataclasses import replace

from chaos_librarian.adapter.compare import compare_fixture_to_observed
from chaos_librarian.adapter.fixture import OracleReports
from chaos_librarian.contract.divergence import CompareMode
from chaos_librarian.contract.observed_state import (
    ObservedAction,
    ObservedEvent,
    ObservedPathHistoryEntry,
)
from chaos_librarian.contract.reports import PathHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName
from tests.support.adapter import fixture as _fixture
from tests.support.adapter import observed as _observed


def _oracle_entry(
    event_id: str,
    action: TimelineActionName,
    *,
    logical_time_ns: int = 1,
    from_path: str | None = None,
    to_path: str | None = None,
    temp_path: str | None = None,
) -> PathHistoryEntry:
    return PathHistoryEntry(
        event_id=event_id,
        action=action,
        logical_time_ns=logical_time_ns,
        from_path=from_path,
        to_path=to_path,
        temp_path=temp_path,
    )


def _fixture_with_history(*entries: PathHistoryEntry):
    fixture = _fixture()
    asset_report = fixture.reports.assets["asset-a"].model_copy(
        update={"path_history": list(entries)}
    )
    reports = OracleReports(
        assets={"asset-a": asset_report},
        works=fixture.reports.works,
        variants=fixture.reports.variants,
        bundles=fixture.reports.bundles,
    )
    return replace(fixture, reports=reports)


def _observed_with_history(*entries: ObservedPathHistoryEntry):
    observed = _observed()
    observed.assets[0].path_history = list(entries)
    return observed


def _history_entry(
    action: str,
    *,
    from_path: str | None = None,
    to_path: str | None = None,
    temp_path: str | None = None,
) -> ObservedPathHistoryEntry:
    return ObservedPathHistoryEntry(
        action=ObservedAction(action),
        from_path=from_path,
        to_path=to_path,
        temp_path=temp_path,
    )


def _global_event(
    action: str,
    *,
    observed_ref: str | None = "observed-a",
    before_observed_ref: str | None = None,
    after_observed_ref: str | None = None,
    from_path: str | None = None,
    to_path: str | None = None,
    temp_path: str | None = None,
) -> ObservedEvent:
    return ObservedEvent(
        observed_event_ref=f"global-{action}",
        observed_ref=observed_ref,
        before_observed_ref=before_observed_ref,
        after_observed_ref=after_observed_ref,
        action=ObservedAction(action),
        from_path=from_path,
        to_path=to_path,
        temp_path=temp_path,
    )


def _compare(fixture, observed):
    return compare_fixture_to_observed(fixture, observed, mode=CompareMode.IDENTITY_HISTORY)


def _codes(report) -> list[str]:
    return [finding.code for finding in report.findings]


def test_identity_history_clean_move_asset() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    )
    observed = _observed_with_history(
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv")
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_clean_rename_file() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "rename-1",
            TimelineActionName.RENAME_FILE,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    )
    observed = _observed_with_history(
        _history_entry("rename_file", from_path="library/old.mkv", to_path="library/new.mkv")
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_clean_archive_file() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "archive-1",
            TimelineActionName.ARCHIVE_FILE,
            from_path="library/old.mkv",
            to_path="archive/old.mkv",
        )
    )
    observed = _observed_with_history(
        _history_entry("archive_file", from_path="library/old.mkv", to_path="archive/old.mkv")
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_clean_move_between_roots() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "root-1",
            TimelineActionName.MOVE_BETWEEN_ROOTS,
            from_path="library/old.mkv",
            to_path="other/old.mkv",
        )
    )
    observed = _observed_with_history(
        _history_entry(
            "move_between_roots",
            from_path="library/old.mkv",
            to_path="other/old.mkv",
        )
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_clean_slow_copy_group() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "slow-start",
            TimelineActionName.SLOW_COPY_START,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
            temp_path="library/.new.tmp",
        ),
        _oracle_entry(
            "slow-commit",
            TimelineActionName.SLOW_COPY_COMMIT,
            to_path="library/new.mkv",
        ),
    )
    observed = _observed_with_history(
        _history_entry(
            "slow_copy_start",
            from_path="library/old.mkv",
            to_path="library/new.mkv",
            temp_path="library/.new.tmp",
        ),
        _history_entry("slow_copy_commit", to_path="library/new.mkv"),
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_clean_delete_add_group() -> None:
    fixture = _fixture_with_history(
        _oracle_entry("delete-1", TimelineActionName.DELETE_FILE, from_path="library/old.mkv"),
        _oracle_entry("add-1", TimelineActionName.ADD_FILE, to_path="library/new.mkv"),
    )
    observed = _observed_with_history(
        _history_entry("delete_file", from_path="library/old.mkv"),
        _history_entry("add_file", to_path="library/new.mkv"),
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_groups_non_adjacent_delete_add_restore() -> None:
    fixture = _fixture_with_history(
        _oracle_entry("delete-1", TimelineActionName.DELETE_FILE, from_path="library/old.mkv"),
        _oracle_entry(
            "sidecar-1",
            TimelineActionName.CREATE_SIDECAR,
            to_path="library/sidecar.srt",
        ),
        _oracle_entry("add-1", TimelineActionName.ADD_FILE, to_path="library/new.mkv"),
    )
    observed = _observed_with_history(
        _history_entry("delete_file", from_path="library/old.mkv"),
        _history_entry("add_file", to_path="library/new.mkv"),
    )

    assert _compare(fixture, observed).ok is True


def test_identity_history_ignores_oracle_create_sidecar_path_history() -> None:
    fixture = _fixture_with_history(
        _oracle_entry("sidecar-1", TimelineActionName.CREATE_SIDECAR, to_path="library/sidecar.srt")
    )

    assert _compare(fixture, _observed()).ok is True


def test_identity_history_missing_all_evidence_emits_history_missing() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    )

    report = _compare(fixture, _observed())

    assert "D_HISTORY_MISSING" in _codes(report)


def test_identity_history_missing_single_event_emits_history_missing() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        ),
        _oracle_entry(
            "rename-1",
            TimelineActionName.RENAME_FILE,
            from_path="library/new.mkv",
            to_path="library/final.mkv",
        ),
    )
    observed = _observed_with_history(
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv")
    )

    report = _compare(fixture, observed)

    assert "D_HISTORY_MISSING" in _codes(report)


def test_duplicate_oracle_lifecycle_requires_duplicate_observed_evidence() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            logical_time_ns=1,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        ),
        _oracle_entry(
            "move-2",
            TimelineActionName.MOVE_ASSET,
            logical_time_ns=2,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        ),
    )
    observed = _observed_with_history(
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv")
    )

    report = _compare(fixture, observed)

    assert "D_HISTORY_MISSING" in _codes(report)


def test_duplicate_observed_lifecycle_without_duplicate_oracle_is_unexpected() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    )
    observed = _observed_with_history(
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv"),
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv"),
    )

    report = _compare(fixture, observed)

    assert "D_HISTORY_UNEXPECTED" in _codes(report)


def test_identity_history_missing_slow_copy_group_reports_related_event_ids() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "slow-start",
            TimelineActionName.SLOW_COPY_START,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
            temp_path="library/.new.tmp",
        ),
        _oracle_entry(
            "slow-commit",
            TimelineActionName.SLOW_COPY_COMMIT,
            to_path="library/new.mkv",
        ),
    )

    report = _compare(fixture, _observed())
    finding = next(finding for finding in report.findings if finding.code == "D_HISTORY_MISSING")

    assert finding.oracle_event_id == "slow-start"
    assert finding.related_oracle_event_ids == ["slow-commit"]


def test_identity_history_split_global_event_emits_identity_split() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    )
    observed = _observed()
    observed.events = [
        _global_event(
            "move_asset",
            observed_ref=None,
            before_observed_ref="observed-a",
            after_observed_ref="observed-b",
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    ]

    report = _compare(fixture, observed)

    assert "D_IDENTITY_SPLIT" in _codes(report)


def test_identity_history_conflict_beats_identity_split() -> None:
    fixture = _fixture_with_history(
        _oracle_entry(
            "move-1",
            TimelineActionName.MOVE_ASSET,
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    )
    observed = _observed_with_history(
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv")
    )
    observed.events = [
        _global_event(
            "move_asset",
            observed_ref=None,
            before_observed_ref="observed-a",
            after_observed_ref="observed-b",
            from_path="library/old.mkv",
            to_path="library/new.mkv",
        )
    ]

    report = _compare(fixture, observed)

    assert "D_HISTORY_CONFLICT" in _codes(report)
    assert "D_IDENTITY_SPLIT" not in _codes(report)


def test_identity_history_unexpected_observed_history_emits_history_unexpected() -> None:
    observed = _observed_with_history(
        _history_entry("move_asset", from_path="library/old.mkv", to_path="library/new.mkv")
    )

    report = _compare(_fixture(), observed)

    assert "D_HISTORY_UNEXPECTED" in _codes(report)
