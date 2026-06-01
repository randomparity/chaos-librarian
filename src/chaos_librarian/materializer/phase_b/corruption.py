"""Deterministic phase-B corruptors for malformed-media profiles."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    ToolInvocation,
)
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import TagCorruptionFlavor, TimelineActionName
from chaos_librarian.materializer.errors import CorruptionActionError, ProbeParseError
from chaos_librarian.materializer.phase_b.content import hash_bytes, hash_file, temp_sibling
from chaos_librarian.materializer.phase_b.corruption_bytes import (
    malformed_id3_header,
    overwrite_range,
    truncate_bytes,
    zero_range,
)
from chaos_librarian.materializer.phase_b.packet_probe import resolve_packet_byte_range
from chaos_librarian.materializer.tooling.constants import STDERR_TAIL_BYTES
from chaos_librarian.materializer.tooling.ffmpeg import run_ffmpeg
from chaos_librarian.materializer.tooling.probe import probe_file

_FFMPEG_POINTER_RE = re.compile(r"(@ )0x[0-9a-fA-F]+")

__all__ = [
    "CorruptionPhaseBContext",
    "apply_corruption_action",
    "make_corruption_phase_b_context",
    "supports_corruption_action",
]


@dataclass(slots=True)
class CorruptionPhaseBContext:
    library_root: Path
    resolved_seed: int
    ffmpeg_version: str = ""
    ffprobe_version: str = ""
    invocations: list[ToolInvocation] = field(default_factory=list)
    post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]] = field(default_factory=dict)


def make_corruption_phase_b_context(
    *,
    library_root: Path,
    resolved_seed: int,
    ffmpeg_version: str,
    ffprobe_version: str,
    invocations: list[ToolInvocation],
) -> CorruptionPhaseBContext:
    return CorruptionPhaseBContext(
        library_root=library_root,
        resolved_seed=resolved_seed,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        invocations=invocations,
    )


def supports_corruption_action(action: TimelineActionName) -> bool:
    return action in _HANDLERS


@dataclass(frozen=True, slots=True)
class _PathPair:
    input_path_rel: str
    output_path_rel: str
    input_path: Path
    output_path: Path


@dataclass(frozen=True, slots=True)
class _FinalizedCorruption:
    paths: _PathPair
    input_content_hash: str
    output_content_hash: str
    input_size_bytes: int
    output_size_bytes: int
    probe_outcome: CorruptionProbeOutcome
    probe_error_tail: str | None
    output_probed: ProbedMedia | None


_Handler = Callable[[CorruptionPhaseBContext, JournalEntry, int], CorruptionAction]


def _probe_corrupted_output(
    output_path: Path,
) -> tuple[CorruptionProbeOutcome, str | None, ProbedMedia | None]:
    try:
        probed = probe_file(output_path)
    except ProbeParseError as exc:
        return CorruptionProbeOutcome.FAILED_EXPECTED, _probe_error_tail(exc), None
    return CorruptionProbeOutcome.STILL_PROBEABLE, None, probed


def _probe_error_tail(exc: ProbeParseError) -> str:
    tail = str(exc.payload.get("stderr") or exc)
    path = exc.payload.get("path")
    if isinstance(path, str) and path:
        tail = tail.replace(path, "<corrupted-output>")
    tail = _FFMPEG_POINTER_RE.sub(r"\1<addr>", tail)
    return tail[-STDERR_TAIL_BYTES:]


def _target_asset_id(entry: JournalEntry) -> str | None:
    return entry.target_ids[0] if entry.target_ids else None


def _output_version_id(entry: JournalEntry) -> str:
    return entry.output_version_ids[0]


def _state_delta_str(delta: dict[str, object], field: str) -> str:
    value = delta[field]
    if not isinstance(value, str):
        raise TypeError(f"state_delta.{field} must be a string")
    return value


def _state_delta_int(delta: dict[str, object], field: str) -> int:
    value = delta[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"state_delta.{field} must be an integer")
    return value


def apply_corruption_action(ctx: CorruptionPhaseBContext, entry: JournalEntry) -> CorruptionAction:
    action = TimelineActionName(entry.action)
    target_asset_id = _target_asset_id(entry)
    started = time.monotonic_ns()
    try:
        handler = _HANDLERS[action]
        return handler(ctx, entry, started)
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


def _apply_corrupt_container_header(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    started: int,
) -> CorruptionAction:
    delta = entry.state_delta
    paths = _paths_from_delta(ctx, delta)
    byte_start = _state_delta_int(delta, "byte_start")
    byte_count = _state_delta_int(delta, "byte_count")
    seed_material = _state_delta_str(delta, "seed_material")
    input_bytes = paths.input_path.read_bytes()
    output_bytes = overwrite_range(
        input_bytes,
        byte_start=byte_start,
        byte_count=byte_count,
        seed_material=seed_material,
    )
    finalized = _write_bytes_and_finalize(ctx, entry, paths, input_bytes, output_bytes)
    return _corruption_action(
        entry=entry,
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        finalized=finalized,
        started=started,
        corruptor=_state_delta_str(delta, "corruptor"),
        byte_start=byte_start,
        byte_count=byte_count,
        seed_material=seed_material,
    )


def _apply_truncate_file(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    started: int,
) -> CorruptionAction:
    delta = entry.state_delta
    paths = _paths_from_delta(ctx, delta)
    keep_bytes = _state_delta_int(delta, "keep_bytes")
    input_bytes = paths.input_path.read_bytes()
    output_bytes = truncate_bytes(input_bytes, keep_bytes=keep_bytes)
    finalized = _write_bytes_and_finalize(ctx, entry, paths, input_bytes, output_bytes)
    return _corruption_action(
        entry=entry,
        action=TimelineActionName.TRUNCATE_FILE,
        finalized=finalized,
        started=started,
        corruptor=_state_delta_str(delta, "corruptor"),
        byte_start=keep_bytes,
        byte_count=len(input_bytes) - keep_bytes,
        seed_material=_state_delta_str(delta, "seed_material"),
    )


def _apply_corrupt_tags(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    started: int,
) -> CorruptionAction:
    delta = entry.state_delta
    paths = _paths_from_delta(ctx, delta)
    flavor = _state_delta_str(delta, "flavor")
    byte_count = _state_delta_int(delta, "byte_count")
    seed_material = _state_delta_str(delta, "seed_material")
    input_bytes = paths.input_path.read_bytes()
    if flavor == TagCorruptionFlavor.NULL_BYTES.value:
        output_bytes = zero_range(input_bytes, byte_start=0, byte_count=byte_count)
    else:
        output_bytes = malformed_id3_header(input_bytes, byte_count=byte_count)
    finalized = _write_bytes_and_finalize(ctx, entry, paths, input_bytes, output_bytes)
    return _corruption_action(
        entry=entry,
        action=TimelineActionName.CORRUPT_TAGS,
        finalized=finalized,
        started=started,
        corruptor=_state_delta_str(delta, "corruptor"),
        byte_start=0,
        byte_count=byte_count,
        seed_material=seed_material,
        metadata={"flavor": flavor},
    )


def _apply_corrupt_packet_range(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    started: int,
) -> CorruptionAction:
    delta = entry.state_delta
    paths = _paths_from_delta(ctx, delta)
    stream = _state_delta_str(delta, "stream")
    packet_start = _state_delta_int(delta, "packet_start")
    packet_count = _state_delta_int(delta, "packet_count")
    seed_material = _state_delta_str(delta, "seed_material")
    byte_start, byte_count = resolve_packet_byte_range(
        paths.input_path,
        stream=stream,
        packet_start=packet_start,
        packet_count=packet_count,
        ffprobe_version=ctx.ffprobe_version,
        invocations=ctx.invocations,
    )
    input_bytes = paths.input_path.read_bytes()
    output_bytes = overwrite_range(
        input_bytes,
        byte_start=byte_start,
        byte_count=byte_count,
        seed_material=seed_material,
    )
    finalized = _write_bytes_and_finalize(ctx, entry, paths, input_bytes, output_bytes)
    return _corruption_action(
        entry=entry,
        action=TimelineActionName.CORRUPT_PACKET_RANGE,
        finalized=finalized,
        started=started,
        corruptor=_state_delta_str(delta, "corruptor"),
        byte_start=byte_start,
        byte_count=byte_count,
        seed_material=seed_material,
        stream=stream,
        packet_start=packet_start,
        packet_count=packet_count,
    )


def _apply_invalid_duration_metadata(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    started: int,
) -> CorruptionAction:
    delta = entry.state_delta
    paths = _paths_from_delta(ctx, delta)
    value = _state_delta_str(delta, "value")
    input_bytes = paths.input_path.read_bytes()
    input_probed = probe_file(paths.input_path)
    temp_output = temp_sibling(paths.output_path, ctx.resolved_seed)
    _run_invalid_duration_copy(
        ctx,
        entry=entry,
        input_path=paths.input_path,
        output_path=temp_output,
        value=value,
    )
    finalized = _finalize_temp_output(ctx, entry, paths, input_bytes, temp_output)
    metadata: dict[str, str | int | float | bool] = {
        "value": value,
        "input_duration_seconds": input_probed.duration_seconds,
    }
    if finalized.output_probed is not None:
        metadata["output_duration_seconds"] = finalized.output_probed.duration_seconds
    return _corruption_action(
        entry=entry,
        action=TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        finalized=finalized,
        started=started,
        corruptor=_state_delta_str(delta, "corruptor"),
        seed_material=_state_delta_str(delta, "seed_material"),
        metadata=metadata,
    )


def _paths_from_delta(ctx: CorruptionPhaseBContext, delta: dict[str, object]) -> _PathPair:
    input_path_rel = _state_delta_str(delta, "input_path")
    output_path_rel = _state_delta_str(delta, "output_path")
    return _PathPair(
        input_path_rel=input_path_rel,
        output_path_rel=output_path_rel,
        input_path=ctx.library_root / input_path_rel,
        output_path=ctx.library_root / output_path_rel,
    )


def _write_bytes_and_finalize(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    paths: _PathPair,
    input_bytes: bytes,
    output_bytes: bytes,
) -> _FinalizedCorruption:
    temp_output = temp_sibling(paths.output_path, ctx.resolved_seed)
    temp_output.write_bytes(output_bytes)
    return _finalize_temp_output(
        ctx,
        entry,
        paths,
        input_bytes,
        temp_output,
        output_bytes=output_bytes,
    )


def _finalize_temp_output(
    ctx: CorruptionPhaseBContext,
    entry: JournalEntry,
    paths: _PathPair,
    input_bytes: bytes,
    temp_output: Path,
    output_bytes: bytes | None = None,
) -> _FinalizedCorruption:
    temp_output.replace(paths.output_path)
    input_hash = hash_bytes(input_bytes)
    if output_bytes is None:
        output_hash = hash_file(paths.output_path)
        output_size_bytes = paths.output_path.stat().st_size
    else:
        output_hash = hash_bytes(output_bytes)
        output_size_bytes = len(output_bytes)
    probe_outcome, probe_error_tail, probed = _probe_corrupted_output(paths.output_path)
    ctx.post_phase_b_versions[_output_version_id(entry)] = (output_hash, probed)
    return _FinalizedCorruption(
        paths=paths,
        input_content_hash=input_hash,
        output_content_hash=output_hash,
        input_size_bytes=len(input_bytes),
        output_size_bytes=output_size_bytes,
        probe_outcome=probe_outcome,
        probe_error_tail=probe_error_tail,
        output_probed=probed,
    )


def _run_invalid_duration_copy(
    ctx: CorruptionPhaseBContext,
    *,
    entry: JournalEntry,
    input_path: Path,
    output_path: Path,
    value: str,
) -> None:
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-metadata",
        f"duration={value}",
        str(output_path),
    ]
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        tail = stderr_tail or "ffmpeg failed"
        raise CorruptionActionError(
            f"write_invalid_duration_metadata failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}: {tail}",
            event_id=entry.event_id,
            action=TimelineActionName.WRITE_INVALID_DURATION_METADATA,
            cause=RuntimeError(f"ffmpeg exit {invocation.exit_code}: {tail}"),
            asset_id=_target_asset_id(entry),
            tool_invocation_index=invocation_index,
        )


def _corruption_action(
    *,
    entry: JournalEntry,
    action: TimelineActionName,
    finalized: _FinalizedCorruption,
    started: int,
    corruptor: str,
    byte_start: int | None = None,
    byte_count: int | None = None,
    seed_material: str | None = None,
    stream: str | None = None,
    packet_start: int | None = None,
    packet_count: int | None = None,
    metadata: dict[str, str | int | float | bool] | None = None,
) -> CorruptionAction:
    return CorruptionAction(
        event_id=entry.event_id,
        action=action,
        target_asset_id=_target_asset_id(entry) or "",
        input_path=finalized.paths.input_path_rel,
        output_path=finalized.paths.output_path_rel,
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=_output_version_id(entry),
        input_content_hash=finalized.input_content_hash,
        output_content_hash=finalized.output_content_hash,
        corruptor=corruptor,
        input_size_bytes=finalized.input_size_bytes,
        output_size_bytes=finalized.output_size_bytes,
        byte_start=byte_start,
        byte_count=byte_count,
        seed_material=seed_material,
        stream=stream,
        packet_start=packet_start,
        packet_count=packet_count,
        metadata=metadata or {},
        probe_outcome=finalized.probe_outcome,
        probe_error_tail=finalized.probe_error_tail,
        duration_ns=time.monotonic_ns() - started,
    )


_HANDLERS: Final[dict[TimelineActionName, _Handler]] = {
    TimelineActionName.CORRUPT_CONTAINER_HEADER: _apply_corrupt_container_header,
    TimelineActionName.TRUNCATE_FILE: _apply_truncate_file,
    TimelineActionName.CORRUPT_PACKET_RANGE: _apply_corrupt_packet_range,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: _apply_invalid_duration_metadata,
    TimelineActionName.CORRUPT_TAGS: _apply_corrupt_tags,
}
