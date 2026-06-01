"""Tests for adapter topology view helpers."""

from __future__ import annotations

from dataclasses import is_dataclass

from chaos_librarian.adapter import topology
from chaos_librarian.adapter.topology import ObservedTopologyView, OracleTopologyView, TopologyKey
from chaos_librarian.contract.domain import ParentKind


def test_topology_domain_fields_are_attribute_based() -> None:
    fields = topology._TopologyDomainFields(movie_title="Synthetic")

    assert is_dataclass(fields)
    assert fields.movie_title == "Synthetic"
    assert not hasattr(fields, "__getitem__")


def test_explicit_topology_key_helpers_use_view_specific_member_counts() -> None:
    oracle_view = OracleTopologyView(
        asset_id="asset-a",
        bundle_id="bundle-a",
        variant_id="variant-a",
        parent_kind=ParentKind.MOVIE,
        parent_id="movie-a",
        movie_title="Synthetic",
        variant_label="hd",
        bundle_asset_ids=("asset-a", "asset-b"),
    )
    observed_view = ObservedTopologyView(
        observed_ref="observed-a",
        bundle_ref="bundle-a",
        variant_ref="variant-a",
        parent_kind=ParentKind.MOVIE,
        parent_ref="movie-a",
        movie_title="Synthetic",
        variant_label="hd",
        bundle_asset_refs=("observed-a",),
    )

    assert topology.oracle_topology_key(oracle_view) == TopologyKey(
        "movie", ("Synthetic", "hd", "2")
    )
    assert topology.observed_topology_key(observed_view) == TopologyKey(
        "movie", ("Synthetic", "hd", "1")
    )


def test_topology_key_constructors_require_kind_specific_fields() -> None:
    assert topology.movie_topology_key(
        movie_title="Synthetic Movie",
        variant_label="hd",
        bundle_member_count=2,
    ) == TopologyKey("movie", ("Synthetic Movie", "hd", "2"))
    assert topology.episode_topology_key(
        series_title="Synthetic Series",
        season_number=1,
        episode_number=3,
        episode_title=None,
        variant_label=None,
        bundle_member_count=1,
    ) == TopologyKey("episode", ("Synthetic Series", "1", "3", "", "", "1"))
    assert topology.track_topology_key(
        artist_name="Synthetic Artist",
        album_title="Synthetic Album",
        disc_number=1,
        track_number=4,
        track_title="Synthetic Track",
        variant_label="deluxe",
        bundle_member_count=1,
    ) == TopologyKey(
        "track",
        ("Synthetic Artist", "Synthetic Album", "1", "4", "Synthetic Track", "deluxe", "1"),
    )
