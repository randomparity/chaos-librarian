"""Tests for chaos_librarian.determinism.seeding."""

from __future__ import annotations

import hashlib

from chaos_librarian.contract.replay_bundle import compute_plan_only_run_id
from chaos_librarian.determinism.seeding import resolve_seed, scenario_content_hash


class TestResolveSeed:
    """resolve_seed normalises declared scenario seeds to integers.

    WHY: Sprint 3 records the result as replay_bundle.resolved_seed so even
    a ``seed: random`` scenario is replayable.
    """

    def test_integer_seed_is_returned_verbatim(self) -> None:
        assert resolve_seed(0) == 0
        assert resolve_seed(42) == 42
        assert resolve_seed(2**63 - 1) == 2**63 - 1

    def test_random_seed_is_a_64_bit_unsigned_integer(self) -> None:
        seed = resolve_seed("random")
        assert isinstance(seed, int)
        assert 0 <= seed < 2**64

    def test_random_seed_varies_across_calls(self) -> None:
        # Probability of a 64-bit collision in 16 draws is ~1.7e-17;
        # if this test fails we have a much bigger problem than flakiness.
        seeds = {resolve_seed("random") for _ in range(16)}
        assert len(seeds) == 16


class TestScenarioContentHash:
    """scenario_content_hash is a stable lowercase hex sha256 of the YAML bytes.

    WHY: this is the hash compute_plan_only_run_id consumes to derive the
    deterministic UUIDv5 run_id; bit-identical bundles require a bit-identical
    hash function across runs.
    """

    def test_matches_hashlib_sha256(self) -> None:
        payload = b"scenario:\n  seed: 42\n"
        assert scenario_content_hash(payload) == hashlib.sha256(payload).hexdigest()

    def test_returns_lowercase_hex_digest(self) -> None:
        digest = scenario_content_hash(b"abc")
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(c in "0123456789abcdef" for c in digest)

    def test_distinct_inputs_hash_differently(self) -> None:
        assert scenario_content_hash(b"a") != scenario_content_hash(b"b")

    def test_feeds_compute_plan_only_run_id(self) -> None:
        # Plan-only run_id derivation must be reproducible across runs given
        # the same scenario bytes and resolved seed.
        payload = b"scenario:\n  seed: 7\n"
        digest = scenario_content_hash(payload)
        run_id_a = compute_plan_only_run_id(digest, 7)
        run_id_b = compute_plan_only_run_id(digest, 7)
        assert run_id_a == run_id_b
