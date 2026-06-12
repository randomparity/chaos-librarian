"""Replay a run dir into per-journal-entry manifest snapshots.

The exporter re-runs the scenario through the same engine path as
``plan``/``replay`` (``build_initial_state`` → ``apply_event`` →
``to_manifest``), snapshotting after every journal entry, and cross-checks
the on-disk journal positionally on ``(event_id, action, phase)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.replay_bundle import ReplayBundle
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.validation import ValidationSeverity, prepare_replay_input_from_bytes
from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    MissingArtifactError,
    ScenarioRevalidationError,
)

_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)
_REPLAY_BUNDLE_ADAPTER: TypeAdapter[ReplayBundle] = TypeAdapter(ReplayBundle)


@dataclass(frozen=True)
class ParsedJournal:
    """On-disk journal entries plus a torn-final-line marker.

    Attributes:
        entries: Successfully parsed entries, in file order.
        ended_mid_write: ``True`` when the final line was an incomplete
            (torn) write that was dropped — the expected shape of a still-
            running or crashed run.
    """

    entries: list[JournalEntry]
    ended_mid_write: bool


def parse_journal_text(text: str) -> ParsedJournal:
    """Parse journal.jsonl text, tolerating a torn final line.

    A final line that fails to parse is treated as the journal head (a torn
    write) and dropped with ``ended_mid_write=True``. Any *non-final*
    unparseable line is corruption and raises ``JournalCorruptLineError``.

    Args:
        text: Raw contents of ``journal.jsonl`` (may be empty).

    Returns:
        A :class:`ParsedJournal`.

    Raises:
        JournalCorruptLineError: a non-final line failed to parse.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    entries: list[JournalEntry] = []
    ended_mid_write = False
    for idx, line in enumerate(lines, start=1):
        try:
            entries.append(_JOURNAL_ADAPTER.validate_json(line))
        except ValidationError as exc:
            if idx == len(lines):
                ended_mid_write = True
                break
            raise JournalCorruptLineError(line=idx, detail=str(exc)) from exc
    return ParsedJournal(entries=entries, ended_mid_write=ended_mid_write)


@dataclass(frozen=True)
class ReplayResult:
    """Per-entry snapshots plus live/planned boundary metadata.

    Attributes:
        snapshots: ``model_dump(mode="json", exclude_none=True)`` of the
            manifest after each *executed* journal entry; ``snapshots[0]`` is
            the seeded initial state, so ``len(snapshots) == live_count + 1``.
            Planned-but-unexecuted steps get no snapshot — the viewer cannot
            scrub into them, so embedding their full library state would only
            inflate the payload.
        events: Every replayed journal entry (live + planned), in order — the
            full list drives the ghosted planned ticks on the strip.
        live_count: Number of entries actually present on disk (the executed
            prefix). Entries at indices ``>= live_count`` are planned.
        total_events: ``len(events)`` — total journal entries emitted across
            the full timeline (may exceed the number of resolved events when
            an action emits more than one entry).
        ended_mid_write: The on-disk journal's final line was a torn write.
        scenario_id / run_id / execution_mode: header metadata.
    """

    snapshots: list[dict[str, object]]
    events: list[JournalEntry]
    live_count: int
    total_events: int
    ended_mid_write: bool
    scenario_id: str
    run_id: str
    execution_mode: str


def _require(run_dir: Path, name: str, produced_by: str) -> Path:
    target = run_dir / name
    if not target.exists():
        raise MissingArtifactError(artifact=name, produced_by=produced_by)
    return target


def _cross_check(disk: list[JournalEntry], replayed: list[JournalEntry]) -> None:
    """Compare on-disk prefix against the replayed sequence on (event_id, action, phase)."""
    if len(disk) > len(replayed):
        extra = disk[len(replayed)]
        raise JournalDivergenceError(
            position=len(replayed),
            disk_event_id=extra.event_id,
            replay_event_id="<past end of timeline>",
        )
    for pos, disk_entry in enumerate(disk):
        replay_entry = replayed[pos]
        if (disk_entry.event_id, disk_entry.action, disk_entry.phase) != (
            replay_entry.event_id,
            replay_entry.action,
            replay_entry.phase,
        ):
            raise JournalDivergenceError(
                position=pos,
                disk_event_id=disk_entry.event_id,
                replay_event_id=replay_entry.event_id,
            )


def replay_with_snapshots(run_dir: Path) -> ReplayResult:
    """Replay ``run_dir`` into per-entry manifest snapshots.

    Reads ``replay.json`` (either execution mode) for the verbatim scenario
    and resolved seed, re-runs the full resolved timeline, and snapshots the
    manifest after each executed journal entry. The on-disk ``journal.jsonl``
    defines the live prefix and is cross-checked positionally.

    Args:
        run_dir: A scenario run directory.

    Returns:
        A :class:`ReplayResult`.

    Raises:
        MissingArtifactError: a required artifact is absent.
        ScenarioRevalidationError: the embedded scenario fails re-validation.
        JournalCorruptLineError: a non-final journal line is unparseable.
        JournalDivergenceError: the on-disk journal disagrees with replay.
    """
    bundle_path = _require(run_dir, "replay.json", "chaos-librarian plan/run")
    # existence guard; bytes come from bundle.scenario
    _require(run_dir, "scenario.yaml", "chaos-librarian plan/run")
    journal_path = _require(run_dir, "journal.jsonl", "chaos-librarian plan/run")

    bundle = _REPLAY_BUNDLE_ADAPTER.validate_json(bundle_path.read_bytes())
    prepared = prepare_replay_input_from_bytes(
        scenario_bytes=bundle.scenario.encode("utf-8"),
        source_label=f"visualize:{bundle.run_id}",
    )
    if not prepared.validation_report.ok:
        # Same guard replay_plan_bundle applies: an older run dir can embed a
        # scenario that no longer validates against the current contract. Fail
        # with a clean ChaosLibrarianError before touching run_input.scenario
        # (a cached_property that would otherwise raise a bare ValidationError).
        codes = [
            issue.code
            for issue in prepared.validation_report.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        raise ScenarioRevalidationError(codes=codes)
    scenario = prepared.run_input.scenario

    recorder = TraceRecorder()
    ids = IdAllocator(recorder)
    state = build_initial_state(scenario, ids)
    ctx = EngineEventContext(
        run_id=bundle.run_id,
        scenario_id=scenario.scenario_id,
        resolved_seed=bundle.resolved_seed,
    )

    parsed = parse_journal_text(journal_path.read_text())
    live_count = len(parsed.entries)

    snapshots: list[dict[str, object]] = [
        state.to_manifest().model_dump(mode="json", exclude_none=True)
    ]
    events: list[JournalEntry] = []
    for resolved in resolve_timeline(scenario):
        for entry in apply_event(state, resolved, ids, ctx):
            events.append(entry)
            # Snapshot only the executed prefix; planned steps are unscrubbable
            # in the viewer, so their snapshots would be dead payload weight.
            if len(events) <= live_count:
                snapshots.append(state.to_manifest().model_dump(mode="json", exclude_none=True))

    _cross_check(parsed.entries, events)

    return ReplayResult(
        snapshots=snapshots,
        events=events,
        live_count=live_count,
        total_events=len(events),
        ended_mid_write=parsed.ended_mid_write,
        scenario_id=scenario.scenario_id,
        run_id=str(bundle.run_id),
        execution_mode=bundle.execution_mode.value,
    )
