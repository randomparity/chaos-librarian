"""Negative-oracle hash phase-B helper."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import OracleHashAction
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import CorruptionActionError
from chaos_librarian.materializer.phase_b.content import hash_file

__all__ = [
    "OracleHashPhaseBContext",
    "apply_wrong_oracle_hash",
    "collided_hash_for",
    "false_hash_for",
    "make_oracle_hash_phase_b_context",
    "supports_oracle_hash_action",
]


@dataclass(slots=True)
class OracleHashPhaseBContext:
    library_root: Path
    post_phase_b_oracle_hashes: dict[str, tuple[str, ProbedMedia | None]] = field(
        default_factory=dict
    )
    version_probe_lookup: Callable[[str], ProbedMedia | None] = lambda _version_id: None


def make_oracle_hash_phase_b_context(
    *,
    library_root: Path,
    version_probe_lookup: Callable[[str], ProbedMedia | None],
    post_phase_b_oracle_hashes: dict[str, tuple[str, ProbedMedia | None]] | None = None,
) -> OracleHashPhaseBContext:
    oracle_hashes = {} if post_phase_b_oracle_hashes is None else post_phase_b_oracle_hashes
    return OracleHashPhaseBContext(
        library_root=library_root,
        post_phase_b_oracle_hashes=oracle_hashes,
        version_probe_lookup=version_probe_lookup,
    )


def supports_oracle_hash_action(action: TimelineActionName) -> bool:
    return action is TimelineActionName.WRONG_ORACLE_HASH


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
    referent's (so the shared prefix is *exactly* ``prefix_len``, not longer),
    and whose full value differs from both ``referent_hash`` and ``real_hash``.

    Pure and deterministic — a function of the two hashes plus ``prefix_len`` —
    so materialize, run, and replay recompute the identical value, mirroring
    ``false_hash_for``.

    Args:
        referent_hash: the ``sha256:``-prefixed digest the prefix is taken from.
        real_hash: this asset's own real on-disk ``sha256:`` digest.
        prefix_len: number of leading hex chars to share (1..63).
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
    """Make ``suffix[0]`` differ from the referent digest at ``prefix_len``.

    Guarantees the shared prefix is exactly ``prefix_len`` chars. A no-op when
    ``prefix_len == 63`` (no char past the prefix exists to constrain) or when
    the suffix is empty.
    """
    if prefix_len >= len(referent_hex) or not suffix:
        return suffix
    if suffix[0] != referent_hex[prefix_len]:
        return suffix
    replacement = "0" if referent_hex[prefix_len] != "0" else "1"
    return replacement + suffix[1:]


def apply_wrong_oracle_hash(
    ctx: OracleHashPhaseBContext,
    entry: JournalEntry,
) -> OracleHashAction:
    action = TimelineActionName(entry.action)
    target_asset_id = _target_asset_id(entry)
    started = time.monotonic_ns()
    try:
        input_path_rel = _state_delta_str(entry.state_delta, "input_path")
        output_path_rel = _state_delta_str(entry.state_delta, "output_path")
        input_version_id = entry.input_version_ids[0] if entry.input_version_ids else None
        output_version_id = _output_version_id(entry)
        seed_material = _state_delta_str(entry.state_delta, "seed_material")
        actual_content_hash = hash_file(ctx.library_root / input_path_rel)
        reported_content_hash = false_hash_for(seed_material, actual_content_hash)
        input_probed = (
            ctx.version_probe_lookup(input_version_id) if input_version_id is not None else None
        )
        ctx.post_phase_b_oracle_hashes[output_version_id] = (
            reported_content_hash,
            input_probed,
        )
        return OracleHashAction(
            event_id=entry.event_id,
            action=TimelineActionName.WRONG_ORACLE_HASH,
            target_asset_id=target_asset_id or "",
            input_path=input_path_rel,
            output_path=output_path_rel,
            input_version_id=input_version_id,
            output_version_id=output_version_id,
            actual_content_hash=actual_content_hash,
            reported_content_hash=reported_content_hash,
            seed_material=seed_material,
            duration_ns=time.monotonic_ns() - started,
        )
    except CorruptionActionError:
        raise
    except Exception as exc:
        raise CorruptionActionError(
            f"{entry.action} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id,
            action=action,
            cause=exc,
            asset_id=target_asset_id,
            tool_invocation_index=getattr(exc, "tool_invocation_index", None),
        ) from exc


def _target_asset_id(entry: JournalEntry) -> str | None:
    return entry.target_ids[0] if entry.target_ids else None


def _output_version_id(entry: JournalEntry) -> str:
    return entry.output_version_ids[0]


def _state_delta_str(delta: dict[str, object], field: str) -> str:
    value = delta[field]
    if not isinstance(value, str):
        raise TypeError(f"state_delta.{field} must be a string")
    return value
