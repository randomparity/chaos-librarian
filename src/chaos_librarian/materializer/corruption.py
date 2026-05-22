"""Deterministic phase-B corruptors for malformed-media profiles."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import CorruptionAction
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import CorruptionActionError, ProbeParseError
from chaos_librarian.materializer.probe import probe_file


@dataclass(slots=True)
class _CorruptionContext:
    library_root: Path
    resolved_seed: int
    post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]] = field(default_factory=dict)


def _replacement_bytes(seed_material: str, byte_count: int) -> bytes:
    output = bytearray()
    block_index = 0
    while len(output) < byte_count:
        block = hashlib.sha256(f"{seed_material}:{block_index}".encode()).digest()
        output.extend(block)
        block_index += 1
    return bytes(output[:byte_count])


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _temp_sibling(output_path: Path, resolved_seed: int) -> Path:
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.tmp.{resolved_seed}{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.tmp.{resolved_seed}")


def _probe_corrupted_output(
    output_path: Path,
) -> tuple[CorruptionProbeOutcome, str | None, ProbedMedia | None]:
    try:
        probed = probe_file(output_path)
    except ProbeParseError as exc:
        return CorruptionProbeOutcome.FAILED_EXPECTED, str(exc)[-2048:], None
    return CorruptionProbeOutcome.STILL_PROBEABLE, None, probed


def _target_asset_id(entry: JournalEntry) -> str | None:
    return entry.target_ids[0] if entry.target_ids else None


def _output_version_id(entry: JournalEntry) -> str:
    return entry.output_version_ids[0]


def apply_corruption_action(ctx: _CorruptionContext, entry: JournalEntry) -> CorruptionAction:
    action = TimelineActionName(entry.action)
    target_asset_id = _target_asset_id(entry)
    started = time.monotonic_ns()
    try:
        delta = entry.state_delta
        input_path = ctx.library_root / str(delta["input_path"])
        output_path = ctx.library_root / str(delta["output_path"])
        byte_start = int(delta["byte_start"])
        byte_count = int(delta["byte_count"])
        seed_material = str(delta["seed_material"])
        input_bytes = input_path.read_bytes()
        required_length = byte_start + byte_count
        if len(input_bytes) < required_length:
            raise ValueError(
                "input file is shorter than requested corruption range: "
                f"{len(input_bytes)} < {required_length}"
            )
        output_bytes = bytearray(input_bytes)
        output_bytes[byte_start:required_length] = _replacement_bytes(seed_material, byte_count)
        temp_output = _temp_sibling(output_path, ctx.resolved_seed)
        temp_output.write_bytes(output_bytes)
        temp_output.replace(output_path)
        final_bytes = output_path.read_bytes()
        input_hash = _hash_bytes(input_bytes)
        output_hash = _hash_bytes(final_bytes)
        probe_outcome, probe_error_tail, probed = _probe_corrupted_output(output_path)
        output_version_id = _output_version_id(entry)
    except Exception as exc:
        if isinstance(exc, ProbeParseError):
            raise
        raise CorruptionActionError(
            f"{entry.action} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id,
            action=action,
            cause=exc,
            asset_id=target_asset_id,
        ) from exc
    ctx.post_phase_b_versions[output_version_id] = (output_hash, probed)
    duration_ns = time.monotonic_ns() - started
    return CorruptionAction(
        event_id=entry.event_id,
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_asset_id=target_asset_id or "",
        input_path=str(entry.state_delta["input_path"]),
        output_path=str(entry.state_delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=output_version_id,
        input_content_hash=input_hash,
        output_content_hash=output_hash,
        corruptor=str(entry.state_delta["corruptor"]),
        byte_start=int(entry.state_delta["byte_start"]),
        byte_count=int(entry.state_delta["byte_count"]),
        seed_material=str(entry.state_delta["seed_material"]),
        probe_outcome=probe_outcome,
        probe_error_tail=probe_error_tail,
        duration_ns=duration_ns,
    )
