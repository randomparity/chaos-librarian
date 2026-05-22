"""Step-mode advance: re-derive cursor state, apply N more events.

``step_fixture`` reads an existing plan-only fixture, verifies it has a
parseable sentinel and matching ``run_id``, recovers world state by
replaying ``resolve_timeline(scenario)`` against the on-disk journal
(verifying every regenerated entry against its counterpart), and then
applies up to ``n_steps`` more step units. The function does NOT write —
the CLI layer calls ``append_step`` to persist the result.

The recovery loop catches hand-edited or duplicated journal lines (every
regenerated entry must equal its on-disk counterpart) and off-step-unit-
boundary lengths (e.g. a journal ending mid-slow_copy-pair: started
without committed).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import (
    PlanOnlyReplayBundle,
    compute_plan_only_run_id,
)
from chaos_librarian.contract.run_sentinel import SENTINEL_FILENAME, RunSentinel
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.reports import ReportSet, build_report_set
from chaos_librarian.engine.resolution import (
    ResolvedEvent,
    resolve_timeline,
    step_boundaries,
)
from chaos_librarian.engine.state import WorldState, build_initial_state
from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.validation import prepare_run_input_from_bytes

_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


class SentinelInvalidError(ChaosLibrarianError):
    """Raised when a run-directory sentinel is missing, unparseable, or stale."""


class ScenarioTamperedError(ChaosLibrarianError):
    """Raised when the on-disk scenario no longer matches bundle.run_id."""

    def __init__(self, *, recorded: str, recomputed: str) -> None:
        super().__init__(
            f"scenario.yaml mutated: recorded run_id {recorded} != recomputed {recomputed}"
        )
        self.recorded = recorded
        self.recomputed = recomputed


class JournalCorruptError(ChaosLibrarianError):
    """Raised when the on-disk journal disagrees with the regenerated prefix.

    Three sub-cases:

    - ``parse``: a journal line fails ``JournalEntry.model_validate_json``.
    - ``entry_mismatch``: a regenerated entry disagrees with the on-disk
      entry (any field).
    - ``off_boundary``: the on-disk journal length doesn't land on a
      step-unit boundary (computed via ``step_boundaries``); a journal
      ending with a slow_copy ``started`` without its ``committed`` is
      the canonical trigger.
    """

    def __init__(self, *, kind: str, line: int | None = None, detail: str = "") -> None:
        super().__init__(f"journal corrupt ({kind}) at line {line}: {detail}".rstrip(": "))
        self.kind = kind
        self.line = line
        self.detail = detail


@dataclass(frozen=True)
class StepResult:
    """In-memory result of one ``step --next N`` invocation."""

    new_entries: tuple[JournalEntry, ...]
    new_current_manifest: Manifest
    new_report_set: ReportSet
    new_replay_bundle: PlanOnlyReplayBundle
    steps_applied: int
    steps_remaining: int
    done: bool


def step_fixture(run_dir: Path, *, n_steps: int) -> StepResult:
    """Advance an existing plan-only fixture by up to ``n_steps`` step units.

    Args:
        run_dir: Existing fixture directory (must carry a parseable
            ``.chaos-librarian-run`` sentinel).
        n_steps: Maximum step units to apply this call. A ``slow_copy_start``
            + ``slow_copy_commit`` adjacent pair is one step unit covering
            two raw journal entries. The CLI layer rejects 0 / negative
            values via Typer's ``min=1``.

    Returns:
        ``StepResult`` describing what was applied. The function never
        writes; the caller persists via ``append_step``.

    Raises:
        SentinelInvalidError: sentinel missing or unparseable.
        ScenarioTamperedError: scenario.yaml mutated since fixture creation.
        JournalCorruptError: on-disk journal disagrees with the
            regenerated prefix or sits at an off-step-unit-boundary length.
    """
    verify_sentinel(run_dir)
    scenario_bytes = (run_dir / "scenario.yaml").read_bytes()
    bundle = PlanOnlyReplayBundle.model_validate_json((run_dir / "replay.json").read_text())
    _verify_scenario_integrity(scenario_bytes, bundle)

    existing_journal = _parse_journal(run_dir / "journal.jsonl")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=f"step:{run_dir}",
    )
    scenario = run_input.scenario
    recorder = TraceRecorder()
    ids = IdAllocator(recorder)
    state = build_initial_state(scenario, ids)
    initial_manifest = state.to_manifest()
    ctx = EngineEventContext(
        run_id=bundle.run_id,
        scenario_id=scenario.scenario_id,
        resolved_seed=bundle.resolved_seed,
    )

    resolved_timeline = resolve_timeline(scenario)
    boundaries = step_boundaries(resolved_timeline)
    cursor_index = _recover_cursor(
        state=state,
        ids=ids,
        resolved_timeline=resolved_timeline,
        existing_journal=existing_journal,
        ctx=ctx,
    )

    # Translate n_steps (step units) → raw event count via boundaries.
    step_at_cursor = 0 if cursor_index == 0 else boundaries.index(cursor_index) + 1
    target_step = min(step_at_cursor + n_steps, len(boundaries))
    target_raw = boundaries[target_step - 1] if target_step > 0 else 0

    new_entries_list: list[JournalEntry] = []
    for resolved in resolved_timeline[cursor_index:target_raw]:
        entries = apply_event(state, resolved, ids, ctx)
        new_entries_list.extend(entries)

    return _finalize_step_result(
        bundle=bundle,
        existing_journal=existing_journal,
        new_entries_list=new_entries_list,
        initial_manifest=initial_manifest,
        state=state,
        recorder=recorder,
        target_raw=target_raw,
        steps_applied=target_step - step_at_cursor,
        steps_remaining=len(boundaries) - target_step,
    )


def _finalize_step_result(
    *,
    bundle: PlanOnlyReplayBundle,
    existing_journal: list[JournalEntry],
    new_entries_list: list[JournalEntry],
    initial_manifest: Manifest,
    state: WorldState,
    recorder: TraceRecorder,
    target_raw: int,
    steps_applied: int,
    steps_remaining: int,
) -> StepResult:
    """Assemble the StepResult after the timeline advance loop."""
    full_journal = existing_journal + new_entries_list
    current_manifest = state.to_manifest()
    report_set = build_report_set(
        initial=initial_manifest,
        current=current_manifest,
        journal=full_journal,
    )
    new_bundle = bundle.model_copy(
        update={
            "applied_events": target_raw,
            "journal_digest": _compute_journal_digest(full_journal),
            "execution_trace": list(recorder.entries()),
        }
    )
    return StepResult(
        new_entries=tuple(new_entries_list),
        new_current_manifest=current_manifest,
        new_report_set=report_set,
        new_replay_bundle=new_bundle,
        steps_applied=steps_applied,
        steps_remaining=steps_remaining,
        done=steps_remaining == 0,
    )


def _compute_journal_digest(journal: list[JournalEntry]) -> str:
    """sha256 of ``serialize_journal_bytes(journal)`` as hex."""
    return hashlib.sha256(serialize_journal_bytes(journal)).hexdigest()


def verify_sentinel(run_dir: Path) -> RunSentinel:
    """Return the parsed sentinel; raise ``SentinelInvalidError`` on missing/unparseable.

    The CLI step/inspect/clean handlers use the parsed value for
    state checks; the engine layer only needs the validation side-effect
    and discards the return value.
    """
    target = run_dir / SENTINEL_FILENAME
    if not target.exists():
        raise SentinelInvalidError(f"sentinel missing: {target}")
    try:
        return RunSentinel.model_validate_json(target.read_text())
    except ValidationError as exc:
        raise SentinelInvalidError(f"sentinel unparseable: {exc}") from exc


def _verify_scenario_integrity(scenario_bytes: bytes, bundle: PlanOnlyReplayBundle) -> None:
    content_hash = hashlib.sha256(scenario_bytes).hexdigest()
    recomputed = compute_plan_only_run_id(content_hash, bundle.resolved_seed)
    if recomputed != bundle.run_id:
        raise ScenarioTamperedError(
            recorded=str(bundle.run_id),
            recomputed=str(recomputed),
        )


def _parse_journal(path: Path) -> list[JournalEntry]:
    if not path.exists():
        return []
    text = path.read_text()
    if not text:
        return []
    entries: list[JournalEntry] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        try:
            entries.append(_JOURNAL_ADAPTER.validate_json(line))
        except ValidationError as exc:
            raise JournalCorruptError(kind="parse", line=idx, detail=str(exc)) from exc
    return entries


def _recover_cursor(
    *,
    state: WorldState,
    ids: IdAllocator,
    resolved_timeline: list[ResolvedEvent],
    existing_journal: list[JournalEntry],
    ctx: EngineEventContext,
) -> int:
    """Replay the timeline until the regenerated journal matches existing_journal.

    Returns the resolved-event index that produced the last on-disk entry,
    or 0 if existing_journal is empty (no apply_event calls performed).
    Raises JournalCorruptError on any mismatch or off-step-unit-boundary length.
    The boundary check uses ``step_boundaries`` so a journal truncated
    mid-slow_copy-pair (started without committed) is rejected.
    """
    if not existing_journal:
        return 0
    boundaries = step_boundaries(resolved_timeline)
    valid = {0, *boundaries}
    matched = 0
    for resolved_index, resolved in enumerate(resolved_timeline):
        regenerated = apply_event(state, resolved, ids, ctx)
        for entry in regenerated:
            if matched >= len(existing_journal):
                raise JournalCorruptError(
                    kind="off_boundary",
                    line=matched,
                    detail=(
                        f"regenerated entry would overshoot mid-event "
                        f"(applied_events_at_cursor={resolved_index}, "
                        f"journal_length={len(existing_journal)})"
                    ),
                )
            disk_entry = existing_journal[matched]
            if entry != disk_entry:
                raise JournalCorruptError(
                    kind="entry_mismatch",
                    line=matched + 1,
                    detail=f"expected {entry!r}, found {disk_entry!r}",
                )
            matched += 1
        if matched == len(existing_journal):
            if matched not in valid:
                raise JournalCorruptError(
                    kind="off_boundary",
                    line=matched,
                    detail=(
                        f"journal length {matched} is not a step-unit boundary "
                        f"(valid: {sorted(valid)})"
                    ),
                )
            return resolved_index + 1
    # Only reachable if existing_journal extends past the resolved timeline
    # (the inner overshoot guard above catches the more common case).
    raise JournalCorruptError(
        kind="off_boundary",
        line=matched,
        detail=(
            f"journal length {len(existing_journal)} did not align with any "
            f"step-unit boundary (matched {matched})"
        ),
    )
