"""Append-only execution-trace recorder.

The recorder owns the canonical sequence of trace entries that downstream
sprints embed in a ReplayBundle. It is the only writer; no third-party
append path exists. Constructor-injected into RngStreams and IdAllocator.
"""

from __future__ import annotations

from chaos_librarian.contract.replay_bundle import (
    AllocTraceEntry,
    ExecutionTraceEntry,
    ExecutionTraceKind,
    MaterializerTraceEntry,
    RngTraceEntry,
)


class TraceRecorder:
    """Append-only buffer of ExecutionTraceEntry values."""

    def __init__(self) -> None:
        self._entries: list[ExecutionTraceEntry] = []

    def record_rng(self, stream: str, value: str) -> None:
        """Append an RngTraceEntry for one RNG draw."""
        self._entries.append(RngTraceEntry(kind=ExecutionTraceKind.RNG, stream=stream, value=value))

    def record_alloc(self, stream: str, value: str) -> None:
        """Append an AllocTraceEntry for one identifier allocation."""
        self._entries.append(
            AllocTraceEntry(kind=ExecutionTraceKind.ALLOC, stream=stream, value=value)
        )

    def record_materializer(self, stream: str, value: str, exit_code: int) -> None:
        """Append a MaterializerTraceEntry for one materializer subprocess.

        Completes the recorder's coverage of the three ExecutionTraceEntry
        variants the contract defines (rng / alloc / materializer). Sprint 5
        builds the materializer's replay bundle directly rather than via
        recorder hand-off; callers that need a recorder-mediated trace path
        for ffmpeg/ffprobe invocations can use this entry point.
        """
        self._entries.append(
            MaterializerTraceEntry(
                kind=ExecutionTraceKind.MATERIALIZER,
                stream=stream,
                value=value,
                exit_code=exit_code,
            )
        )

    def entries(self) -> tuple[ExecutionTraceEntry, ...]:
        """Return an immutable tuple snapshot of recorded entries.

        Pydantic accepts tuples for ``list[...]`` fields during serialization,
        so Sprint 3's plan-only assembler can pass the snapshot through to
        the replay bundle without an extra copy step.
        """
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
