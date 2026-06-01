"""Pure content-hash policy helpers shared by materializer phases."""

from __future__ import annotations

import hashlib

__all__ = ["collided_hash_for", "false_hash_for"]


def false_hash_for(seed_material: str, actual_hash: str) -> str:
    suffix = hashlib.sha256(f"{seed_material}:{actual_hash}".encode()).hexdigest()
    candidate = f"sha256:{suffix}"
    if candidate != actual_hash:
        return candidate
    fallback = hashlib.sha256(f"{seed_material}:{actual_hash}:fallback".encode()).hexdigest()
    return f"sha256:{fallback}"


def collided_hash_for(referent_hash: str, real_hash: str, prefix_len: int) -> str:
    """Return a recorded hash sharing exactly ``prefix_len`` leading hex chars.

    Builds the oracle-recorded content hash for a ``hash_collision_with`` asset:
    a valid ``sha256:`` URI whose first ``prefix_len`` hex chars equal the
    referent's recorded digest, whose char at ``prefix_len`` differs from the
    referent's so the shared prefix is exactly ``prefix_len``, and whose full
    value differs from both ``referent_hash`` and ``real_hash``.
    """
    referent_hex = referent_hash.removeprefix("sha256:")
    prefix = referent_hex[:prefix_len]
    suffix = hashlib.sha256(f"{real_hash}:{referent_hash}:{prefix_len}".encode()).hexdigest()[
        prefix_len:
    ]
    suffix = _force_divergent_first_char(suffix, referent_hex, prefix_len)
    candidate = f"sha256:{prefix}{suffix}"
    if candidate in (referent_hash, real_hash):
        suffix = hashlib.sha256(f"{candidate}:fallback".encode()).hexdigest()[prefix_len:]
        suffix = _force_divergent_first_char(suffix, referent_hex, prefix_len)
        candidate = f"sha256:{prefix}{suffix}"
    return candidate


def _force_divergent_first_char(suffix: str, referent_hex: str, prefix_len: int) -> str:
    """Make ``suffix[0]`` differ from the referent digest at ``prefix_len``."""
    if prefix_len >= len(referent_hex) or not suffix:
        return suffix
    if suffix[0] != referent_hex[prefix_len]:
        return suffix
    replacement = "0" if referent_hex[prefix_len] != "0" else "1"
    return replacement + suffix[1:]
