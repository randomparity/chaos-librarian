"""Tests for fuzz profile/lane metadata."""

from __future__ import annotations

from chaos_librarian.contract.profiles import (
    CANONICAL_FUZZ_LANES,
    FUZZ_LANES_BY_PROFILE,
    FuzzProfileName,
)


def test_canonical_lane_order_covers_each_profile_exactly() -> None:
    assert set(CANONICAL_FUZZ_LANES) == set(FuzzProfileName)
    for profile, order in CANONICAL_FUZZ_LANES.items():
        # ordered tuple and the existing frozenset must not drift apart
        assert frozenset(order) == FUZZ_LANES_BY_PROFILE[profile]
        # no duplicates in the ordered tuple
        assert len(order) == len(set(order))
