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
