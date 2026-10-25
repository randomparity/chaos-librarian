"""Tests for fuzz profile/lane metadata."""

from __future__ import annotations

from chaos_librarian.contract.profile_policy import REQUIRED_PROFILES_BY_ACTION
from chaos_librarian.contract.profiles import (
    CANONICAL_FUZZ_LANES,
    FUZZ_LANES_BY_PROFILE,
    FuzzLaneName,
    FuzzProfileName,
    ProfileName,
)
from chaos_librarian.contract.scenario import TimelineActionName


def test_canonical_lane_order_covers_each_profile_exactly() -> None:
    assert set(CANONICAL_FUZZ_LANES) == set(FuzzProfileName)
    for profile, order in CANONICAL_FUZZ_LANES.items():
        # ordered tuple and the existing frozenset must not drift apart
        explicit = (
            {FuzzLaneName.ADVERSARIAL_MEDIA}
            if profile is FuzzProfileName.FUZZ_REGRESSION
            else set()
        )
        assert frozenset(order) | explicit == FUZZ_LANES_BY_PROFILE[profile]
        assert not (frozenset(order) & explicit)
        # no duplicates in the ordered tuple
        assert len(order) == len(set(order))


def test_profile_gated_action_policy_uses_contract_enums() -> None:
    assert REQUIRED_PROFILES_BY_ACTION[TimelineActionName.CORRUPT_TAGS] is (
        ProfileName.MALFORMED_MEDIA
    )
    assert set(REQUIRED_PROFILES_BY_ACTION).issubset(set(TimelineActionName))
    assert set(REQUIRED_PROFILES_BY_ACTION.values()).issubset(set(ProfileName))
