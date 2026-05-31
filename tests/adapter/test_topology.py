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
