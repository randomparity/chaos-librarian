"""Runtime helpers for seed resolution and scenario content hashing.

These functions live next to the deterministic primitives because they are
runtime inputs — not schemas — to RngStreams construction and to the
plan-only run_id derivation in contract.replay_bundle.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Literal


def resolve_seed(declared: int | Literal["random"]) -> int:
    """Return a concrete integer seed for the run.

    Args:
        declared: Either an integer (returned verbatim) or the string
            ``"random"`` (drawn from ``secrets.randbits(64)``).

    Returns:
        Non-negative integer seed; in the ``"random"`` branch the value is
        in ``[0, 2**64)``.
    """
    if declared == "random":
        return secrets.randbits(64)
    return declared


def scenario_content_hash(scenario_yaml_bytes: bytes) -> str:
    """Return the lowercase hex sha256 digest of the verbatim scenario YAML bytes.

    Sprint 3 passes this digest into
    ``chaos_librarian.contract.replay_bundle.compute_plan_only_run_id`` to
    derive the deterministic UUIDv5 ``run_id`` for plan-only bundles.
    """
    return hashlib.sha256(scenario_yaml_bytes).hexdigest()
