from __future__ import annotations

import pytest

from chaos_librarian.adapter.history import compare_identity_history
from chaos_librarian.adapter.index import (
    ObservedAssetView,
    ObservedIndex,
    OracleAssetView,
    OracleIndex,
)
from chaos_librarian.adapter.matching import AssetMatch, MatchResult
from chaos_librarian.contract.divergence import DivergenceCode
from chaos_librarian.contract.observed_state import (
    ObservedAction,
    ObservedEvent,
    ObservedPathHistoryEntry,
)
from chaos_librarian.contract.reports import PathHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.errors import ChaosLibrarianError


def _oracle_entry(
    event_id: str,
    action: TimelineActionName,
    *,
    logical_time_ns: int,
    from_path: str | None = None,
    to_path: str | None = None,
) -> PathHistoryEntry:
    return PathHistoryEntry(
        event_id=event_id,
        action=action,
        logical_time_ns=logical_time_ns,
        from_path=from_path,
        to_path=to_path,
        temp_path=None,
    )


def _observed_entry(
    action: ObservedAction,
    *,
    from_path: str | None = None,
    to_path: str | None = None,
) -> ObservedPathHistoryEntry:
    return ObservedPathHistoryEntry(action=action, from_path=from_path, to_path=to_path)


def _oracle_index(*entries: PathHistoryEntry) -> OracleIndex:
    return OracleIndex.from_views(
        assets=[
            OracleAssetView(
                asset_id="asset-a",
                bundle_id="bundle-a",
                current_path="library/current.mkv",
                content_hash=None,
                probed=None,
                path_history=entries,
                sidecars=(),
            )
        ]
    )


def _observed_index(
    *entries: ObservedPathHistoryEntry,
    events: tuple[ObservedEvent, ...] = (),
) -> ObservedIndex:
    return ObservedIndex.from_views(
        assets=[
            ObservedAssetView(
                observed_ref="observed-a",
                current_path="library/current.mkv",
                content_hash=None,
                probed=None,
                variant_ref=None,
                bundle_ref=None,
                sidecars=(),
                path_history=entries,
            )
        ],
        events=events,
    )


def _match_result() -> MatchResult:
    return MatchResult(
        matches=(AssetMatch(oracle_asset_id="asset-a", observed_ref="observed-a", evidence=()),),
        findings=(),
        unmatched_oracle_asset_ids=(),
        unmatched_observed_refs=(),
        ambiguous_oracle_asset_ids=(),
        ambiguous_observed_refs=(),
    )


def test_compare_identity_history_groups_delete_add_lifecycle() -> None:
    findings = compare_identity_history(
        _match_result(),
        _oracle_index(
            _oracle_entry(
                "delete-1",
                TimelineActionName.DELETE_FILE,
                logical_time_ns=1,
                from_path="library/old.mkv",
            ),
            _oracle_entry(
                "add-1",
                TimelineActionName.ADD_FILE,
                logical_time_ns=2,
                to_path="library/new.mkv",
            ),
        ),
        _observed_index(
            _observed_entry(
                ObservedAction.DELETE_FILE,
                from_path="library/old.mkv",
            ),
            _observed_entry(
                ObservedAction.ADD_FILE,
                to_path="library/new.mkv",
            ),
        ),
    )

    assert findings == ()


def test_compare_identity_history_reports_conflicting_observed_candidates() -> None:
    findings = compare_identity_history(
        _match_result(),
        _oracle_index(
            _oracle_entry(
                "move-1",
                TimelineActionName.MOVE_ASSET,
                logical_time_ns=1,
                from_path="library/old.mkv",
                to_path="library/new.mkv",
            )
        ),
        _observed_index(
            _observed_entry(
                ObservedAction.MOVE_ASSET,
                from_path="library/old.mkv",
                to_path="library/new.mkv",
            ),
            events=(
                ObservedEvent(
                    observed_event_ref="global-move",
                    action=ObservedAction.MOVE_ASSET,
                    before_observed_ref="observed-a",
                    after_observed_ref="observed-b",
                    from_path="library/old.mkv",
                    to_path="library/new.mkv",
                ),
            ),
        ),
    )

    assert [finding.code for finding in findings] == [DivergenceCode.HISTORY_CONFLICT]
    assert findings[0].observed == {
        "identity_pairs": [
            {"source": "path_history", "before": "observed-a", "after": "observed-a"},
            {"source": "global", "before": "observed-a", "after": "observed-b"},
        ]
    }


def test_compare_identity_history_defensive_global_event_error_uses_library_base() -> None:
    invalid_event = ObservedEvent(
        observed_event_ref="global-move",
        action=ObservedAction.MOVE_ASSET,
        before_observed_ref="observed-a",
        after_observed_ref="observed-b",
        from_path="library/old.mkv",
        to_path="library/new.mkv",
    ).model_copy(update={"after_observed_ref": None})

    with pytest.raises(ChaosLibrarianError, match="missing identity refs"):
        compare_identity_history(
            _match_result(),
            _oracle_index(
                _oracle_entry(
                    "move-1",
                    TimelineActionName.MOVE_ASSET,
                    logical_time_ns=1,
                    from_path="library/old.mkv",
                    to_path="library/new.mkv",
                )
            ),
            _observed_index(events=(invalid_event,)),
        )
