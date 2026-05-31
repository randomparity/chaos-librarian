"""Tests for adapter topology view helpers."""

from __future__ import annotations

from dataclasses import is_dataclass

from chaos_librarian.adapter import topology


def test_topology_domain_fields_are_attribute_based() -> None:
    fields = topology._TopologyDomainFields(movie_title="Synthetic")

    assert is_dataclass(fields)
    assert fields.movie_title == "Synthetic"
    assert not hasattr(fields, "__getitem__")
