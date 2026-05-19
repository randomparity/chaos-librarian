"""Plan-only orchestrator and bundle-driven replay helper.

``run_plan`` consumes a pre-read ``RunInput`` plus a validation report,
walks the timeline, and returns the complete set of in-memory artifacts.
Persistence is delegated to ``chaos_librarian.engine.writer.write_fixture``.

``replay_plan_bundle`` re-runs ``plan`` from a recorded ``PlanOnlyReplayBundle``
so a previously emitted fixture can be reproduced from its bundle alone.
Sprint 4 wraps it in the public ``replay`` CLI command.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    PlanOnlyReplayBundle,
    compute_plan_only_run_id,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.determinism import (
    IdAllocator,
    TraceRecorder,
    resolve_seed,
)
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.reports import ReportSet, build_report_set
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.validation import (
    RunInput,
    prepare_run_input_from_bytes,
    run_validation,
)


@dataclass(frozen=True)
class PlanArtifacts:
    """In-memory result of a plan-only run, prior to persistence."""

    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    replay_bundle: PlanOnlyReplayBundle
    validation_report: ValidationReport
    sentinel: RunSentinel
    reports: ReportSet


def run_plan(
    *,
    run_input: RunInput,
    validation_report: ValidationReport,
    resolved_seed_override: int | None = None,
    steps_limit: int | None = None,
) -> PlanArtifacts:
    """Walk the scenario carried by ``run_input`` and assemble every plan-only artifact.

    Args:
        run_input: A frozen, byte-bound read of the scenario. ``raw_bytes``
            is embedded in the replay bundle; ``content_hash`` derives the
            deterministic ``run_id``.
        validation_report: The Sprint 1 report; serialized into the fixture
            as ``validation.json``. Must be ``ok=True`` if the caller wants
            a real fixture, but ``run_plan`` does not re-check.
        resolved_seed_override: Internal-only. When set, skip
            ``resolve_seed`` and use this value instead. ``replay_plan_bundle``
            passes ``bundle.resolved_seed`` so ``seed: random`` scenarios
            reproduce the recorded seed instead of redrawing.
        steps_limit: Cap on resolved events to apply, counted in step units.
            ``None`` (default) runs the entire timeline. ``0`` produces an
            empty journal and ``current_manifest == initial_manifest``.
            Values above ``len(step_boundaries(resolve_timeline(parsed)))``
            are clamped silently. A ``slow_copy_start`` + ``slow_copy_commit``
            adjacent pair counts as one step (advances together).

    Returns:
        ``PlanArtifacts`` ready to hand to ``write_fixture``.
    """
    parsed = Scenario.model_validate(run_input.raw_data)
    resolved_seed = (
        resolved_seed_override if resolved_seed_override is not None else resolve_seed(parsed.seed)
    )
    recorder = TraceRecorder()
    ids = IdAllocator(recorder)

    initial_state = build_initial_state(parsed, ids)
    initial_manifest = initial_state.to_manifest()

    resolved_timeline = resolve_timeline(parsed)
    boundaries = step_boundaries(resolved_timeline)
    if steps_limit is None:
        applied_events = boundaries[-1] if boundaries else 0
    elif steps_limit <= 0:
        applied_events = 0
    elif steps_limit >= len(boundaries):
        applied_events = boundaries[-1] if boundaries else 0
    else:
        applied_events = boundaries[steps_limit - 1]

    run_id = compute_plan_only_run_id(
        scenario_content_hash=run_input.content_hash,
        resolved_seed=resolved_seed,
    )

    journal: list[JournalEntry] = []
    for resolved in resolved_timeline[:applied_events]:
        entries = apply_event(
            initial_state,
            resolved,
            ids,
            run_id,
            parsed.scenario_id,
        )
        journal.extend(entries)

    current_manifest = initial_state.to_manifest()

    reports = build_report_set(
        initial=initial_manifest,
        current=current_manifest,
        journal=journal,
    )

    journal_digest = hashlib.sha256(serialize_journal_bytes(journal)).hexdigest()

    bundle = PlanOnlyReplayBundle(
        schema_version=2,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=run_input.raw_bytes.decode("utf-8"),
        run_id=run_id,
        resolved_seed=resolved_seed,
        applied_events=applied_events,
        journal_digest=journal_digest,
        execution_trace=list(recorder.entries()),
        execution_mode=ExecutionMode.PLAN_ONLY,
    )

    sentinel = RunSentinel(
        run_id=run_id,
        schema_version=1,
        created_by=f"chaos-librarian {_chaos_librarian_version}",
        # created_at omitted in plan-only — see "Filesystem Safety".
        created_at=None,
    )

    return PlanArtifacts(
        initial_manifest=initial_manifest,
        current_manifest=current_manifest,
        journal=tuple(journal),
        replay_bundle=bundle,
        validation_report=validation_report,
        sentinel=sentinel,
        reports=reports,
    )


class ReplayIntegrityError(RuntimeError):
    """Raised when a replay bundle's integrity check fails.

    Three independent checks live in ``replay_plan_bundle``:

    1. Scenario / seed tampering: the recomputed ``run_id`` does not
       match ``bundle.run_id``. The bundle's ``scenario`` text or
       ``resolved_seed`` has been modified relative to the recorded
       ``run_id``.
    2. ``applied_events`` is not on a step boundary. A slow_copy pair
       must be entirely present or entirely absent; mid-pair counts are
       nonsensical and indicate tampering.
    3. ``journal_digest`` mismatch. Catches ``applied_events`` flipped
       between two valid boundary values (run_id check still passes,
       but the recomputed journal's bytes no longer match the recorded
       digest).
    """


def replay_plan_bundle(bundle: PlanOnlyReplayBundle) -> PlanArtifacts:
    """Re-run ``plan`` from a recorded plan-only bundle.

    Takes the bundle's verbatim ``scenario`` field, treats it as the
    canonical bytes for the replay run, and returns a ``PlanArtifacts``
    record identical to the original run on success. Sprint 4 wraps this
    helper in the public ``chaos-librarian replay`` CLI command and adds
    divergence reporting (exit 6).

    Three integrity checks fire in order before returning artifacts:

    1. ``applied_events`` must sit on a step-unit boundary derived from the
       resolved timeline (Codex round 3 finding 1 — mid-pair counts are
       nonsensical because a ``slow_copy_start`` + ``slow_copy_commit`` pair
       advances together as one step).
    2. The recomputed ``run_id`` must match ``bundle.run_id`` — catches
       tampering of ``bundle.scenario`` text or ``bundle.resolved_seed``.
    3. The recomputed ``journal_digest`` must match ``bundle.journal_digest``
       (Codex round 3 finding 2 — without this, flipping ``applied_events``
       between two valid boundaries would silently produce a longer fixture).

    After the boundary check passes, ``bundle.applied_events`` (translated
    from a raw-event count to a step-unit count) is threaded through to
    ``run_plan`` as ``steps_limit`` so a partial bundle replays as the same
    partial fixture.

    Raises:
        ReplayIntegrityError: if any of the three integrity checks fails —
            ``bundle.applied_events`` is not on a step-unit boundary, the
            recomputed ``run_id`` disagrees with ``bundle.run_id`` (scenario
            or seed tampering), or the recomputed ``journal_digest`` does
            not match ``bundle.journal_digest`` (``applied_events`` flipped
            between two valid boundaries).
    """
    yaml_bytes = bundle.scenario.encode("utf-8")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=yaml_bytes,
        source_label=f"replay:{bundle.run_id}",
    )
    report = run_validation(run_input)
    if not report.ok:
        errors = [i.code for i in report.issues if i.severity == ValidationSeverity.ERROR]
        raise RuntimeError(f"replay scenario re-validation failed: {errors}")

    parsed = Scenario.model_validate(run_input.raw_data)
    resolved_timeline = resolve_timeline(parsed)
    boundaries = step_boundaries(resolved_timeline)
    valid_boundaries = {0, *boundaries}
    if bundle.applied_events not in valid_boundaries:
        raise ReplayIntegrityError(
            f"applied_events {bundle.applied_events} is not on a step boundary "
            f"(valid: {sorted(valid_boundaries)})"
        )

    # Safe: boundary check above proved applied_events is in {0, *boundaries}.
    step_count = 0 if bundle.applied_events == 0 else boundaries.index(bundle.applied_events) + 1

    artifacts = run_plan(
        run_input=run_input,
        validation_report=report,
        resolved_seed_override=bundle.resolved_seed,
        steps_limit=step_count,
    )

    recomputed = artifacts.replay_bundle.run_id
    if recomputed != bundle.run_id:
        raise ReplayIntegrityError(
            f"replay bundle integrity check failed: recorded run_id {bundle.run_id} "
            f"does not match recomputed run_id {recomputed} "
            f"(bundle.scenario or bundle.resolved_seed has been modified)"
        )

    if artifacts.replay_bundle.journal_digest != bundle.journal_digest:
        raise ReplayIntegrityError(
            f"journal_digest mismatch: recorded {bundle.journal_digest}, "
            f"recomputed {artifacts.replay_bundle.journal_digest}"
        )

    return artifacts
