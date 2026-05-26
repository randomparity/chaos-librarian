"""Tests for adapter evidence indexing and deterministic asset matching."""

from __future__ import annotations

from chaos_librarian.adapter.index import (
    ObservedAssetView,
    ObservedIndex,
    ObservedTopologyView,
    OracleAssetView,
    OracleIndex,
    OracleTopologyView,
)
from chaos_librarian.adapter.matching import match_assets
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.reports import PathHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_1 = "sha256:" + "1" * 64
HASH_2 = "sha256:" + "2" * 64


def _oracle_asset(
    asset_id: str,
    *,
    current_path: str | None = None,
    content_hash: str | None = None,
    path_history: tuple[PathHistoryEntry, ...] = (),
) -> OracleAssetView:
    return OracleAssetView(
        asset_id=asset_id,
        bundle_id=f"bundle-{asset_id}",
        current_path=current_path,
        content_hash=content_hash,
        probed=None,
        path_history=path_history,
        sidecars=(),
    )


def _observed_asset(
    observed_ref: str,
    *,
    current_path: str | None = None,
    content_hash: str | None = None,
) -> ObservedAssetView:
    return ObservedAssetView(
        observed_ref=observed_ref,
        current_path=current_path,
        content_hash=content_hash,
        probed=None,
        variant_ref=None,
        bundle_ref=None,
        sidecars=(),
        path_history=(),
    )


def _indexes(
    oracle_assets: tuple[OracleAssetView, ...],
    observed_assets: tuple[ObservedAssetView, ...],
    *,
    oracle_topology: tuple[OracleTopologyView, ...] = (),
    observed_topology: tuple[ObservedTopologyView, ...] = (),
) -> tuple[OracleIndex, ObservedIndex]:
    oracle = OracleIndex.from_views(assets=oracle_assets, topology=oracle_topology)
    observed = ObservedIndex.from_views(assets=observed_assets, topology=observed_topology)
    return oracle, observed


def _history_path(path: str) -> PathHistoryEntry:
    return PathHistoryEntry(
        event_id="event-1",
        action=TimelineActionName.MOVE_ASSET,
        logical_time_ns=1,
        from_path=path,
        to_path="library/new.mkv",
    )


def _oracle_topology(asset_id: str, *, title: str, label: str) -> OracleTopologyView:
    return OracleTopologyView(
        asset_id=asset_id,
        bundle_id=f"oracle-bundle-{asset_id}",
        variant_id=f"oracle-variant-{asset_id}",
        parent_kind=ParentKind.MOVIE,
        parent_id=f"oracle-movie-{asset_id}",
        parent_title=title,
        variant_label=label,
        bundle_asset_ids=(asset_id,),
    )


def _observed_topology(observed_ref: str, *, title: str, label: str) -> ObservedTopologyView:
    return ObservedTopologyView(
        observed_ref=observed_ref,
        bundle_ref=f"observed-bundle-{observed_ref}",
        variant_ref=f"observed-variant-{observed_ref}",
        parent_kind=ParentKind.MOVIE,
        parent_ref=f"observed-movie-{observed_ref}",
        parent_title=title,
        variant_label=label,
        bundle_asset_refs=(observed_ref,),
    )


def test_matches_by_unique_current_path_before_hash() -> None:
    oracle, observed = _indexes(
        (
            _oracle_asset("oracle-a", current_path="library/a.mkv", content_hash=HASH_1),
            _oracle_asset("oracle-b", current_path="library/b.mkv", content_hash=HASH_2),
        ),
        (
            _observed_asset("observed-a", current_path="library/a.mkv", content_hash=HASH_2),
            _observed_asset("observed-b", current_path="library/c.mkv", content_hash=HASH_2),
        ),
    )

    result = match_assets(oracle, observed)

    assert [(match.oracle_asset_id, match.observed_ref) for match in result.matches] == [
        ("oracle-a", "observed-a"),
        ("oracle-b", "observed-b"),
    ]
    assert result.matches[0].evidence[0].kind == "current_path"


def test_matches_deleted_asset_by_historical_path() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a", path_history=(_history_path("library/deleted.mkv"),)),),
        (_observed_asset("observed-a", current_path="library/deleted.mkv"),),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].oracle_asset_id == "oracle-a"
    assert result.matches[0].evidence[0].kind == "historical_path"


def test_matches_by_hash_when_paths_are_absent() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a", content_hash=HASH_A),),
        (_observed_asset("observed-a", content_hash=HASH_A),),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].observed_ref == "observed-a"
    assert result.matches[0].evidence[0].kind == "content_hash"


def test_matches_by_unique_topology_when_path_and_hash_absent() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a"),),
        (_observed_asset("observed-a"),),
        oracle_topology=(_oracle_topology("oracle-a", title="Synthetic", label="hd"),),
        observed_topology=(_observed_topology("observed-a", title="Synthetic", label="hd"),),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].oracle_asset_id == "oracle-a"
    assert result.matches[0].evidence[0].kind == "topology"


def test_topology_matching_ignores_oracle_ids_and_observed_refs() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("asset-oracle-id"),),
        (_observed_asset("completely-different-observed-ref"),),
        oracle_topology=(_oracle_topology("asset-oracle-id", title="Same Title", label="hd"),),
        observed_topology=(
            _observed_topology(
                "completely-different-observed-ref",
                title="Same Title",
                label="hd",
            ),
        ),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].observed_ref == "completely-different-observed-ref"


def test_topology_match_records_match_evidence() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a"),),
        (_observed_asset("observed-a"),),
        oracle_topology=(_oracle_topology("oracle-a", title="Synthetic", label="4k"),),
        observed_topology=(_observed_topology("observed-a", title="Synthetic", label="4k"),),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].evidence[0].value == "Synthetic|4k|1"


def test_topology_ambiguity_emits_d_match_ambiguous() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a"), _oracle_asset("oracle-b")),
        (_observed_asset("observed-a"),),
        oracle_topology=(
            _oracle_topology("oracle-a", title="Synthetic", label="hd"),
            _oracle_topology("oracle-b", title="Synthetic", label="hd"),
        ),
        observed_topology=(_observed_topology("observed-a", title="Synthetic", label="hd"),),
    )

    result = match_assets(oracle, observed)

    assert result.findings[0].code == "D_MATCH_AMBIGUOUS"
    assert result.ambiguous_oracle_asset_ids == ("oracle-a", "oracle-b")
    assert result.ambiguous_observed_refs == ("observed-a",)


def test_unique_higher_precedence_match_wins_over_lower_conflict() -> None:
    oracle, observed = _indexes(
        (
            _oracle_asset("oracle-a", current_path="library/a.mkv", content_hash=HASH_B),
            _oracle_asset("oracle-b", current_path="library/b.mkv", content_hash=HASH_A),
        ),
        (
            _observed_asset("observed-a", current_path="library/a.mkv", content_hash=HASH_A),
            _observed_asset("observed-b", current_path="library/b.mkv", content_hash=HASH_B),
        ),
    )

    result = match_assets(oracle, observed)

    assert [(match.oracle_asset_id, match.observed_ref) for match in result.matches] == [
        ("oracle-a", "observed-a"),
        ("oracle-b", "observed-b"),
    ]


def test_observed_asset_mapping_to_two_oracles_is_ambiguous() -> None:
    oracle, observed = _indexes(
        (
            _oracle_asset("oracle-a", content_hash=HASH_A),
            _oracle_asset("oracle-b", content_hash=HASH_A),
        ),
        (_observed_asset("observed-a", content_hash=HASH_A),),
    )

    result = match_assets(oracle, observed)

    assert result.matches == ()
    assert result.findings[0].code == "D_MATCH_AMBIGUOUS"


def test_oracle_asset_mapping_to_two_observed_assets_is_ambiguous() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a", content_hash=HASH_A),),
        (
            _observed_asset("observed-a", content_hash=HASH_A),
            _observed_asset("observed-b", content_hash=HASH_A),
        ),
    )

    result = match_assets(oracle, observed)

    assert result.matches == ()
    assert result.ambiguous_observed_refs == ("observed-a", "observed-b")


def test_ambiguous_candidates_do_not_also_emit_missing_or_unexpected() -> None:
    oracle, observed = _indexes(
        (
            _oracle_asset("oracle-a", content_hash=HASH_A),
            _oracle_asset("oracle-b", content_hash=HASH_A),
        ),
        (_observed_asset("observed-a", content_hash=HASH_A),),
    )

    result = match_assets(oracle, observed)

    assert [finding.code for finding in result.findings] == ["D_MATCH_AMBIGUOUS"]


def test_unmatched_oracle_asset_emits_asset_missing() -> None:
    oracle, observed = _indexes((_oracle_asset("oracle-a"),), ())

    result = match_assets(oracle, observed)

    assert result.findings[0].code == "D_ASSET_MISSING"
    assert result.findings[0].oracle_asset_id == "oracle-a"


def test_unmatched_observed_asset_emits_asset_unexpected() -> None:
    oracle, observed = _indexes((), (_observed_asset("observed-a"),))

    result = match_assets(oracle, observed)

    assert result.findings[0].code == "D_ASSET_UNEXPECTED"
    assert result.findings[0].observed_ref == "observed-a"
