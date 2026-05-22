# Sprint 10 Extended Profiles Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Sprint 10 malformed-media foundation: explicit profile
opt-in, one deterministic container-header corruptor, corruption metadata in
contracts and reports, and replayable materialized output.

**Architecture:** Keep the engine pure: it allocates the new version, records
corruption intent, and writes deterministic seed material into the journal. Add
a materializer-only corruption dispatcher beside the existing stdlib and media
phase-B dispatchers; it mutates bytes, hashes output, probes the result, and
returns audit records. Reports are regenerated from the final augmented
manifest so asset reports match `manifest.current.json`.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, pytest, ruff, ty, existing
ffmpeg and ffprobe capability gates. No new dependencies.

---

## Source Inputs

**Design doc:** `docs/superpowers/specs/`
`2026-05-22-sprint-10-extended-profiles-foundation-design.md`

**Primary source:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)

**Deferred issues already filed:** #70, #71, #72, #73, #74, #75.

**Execution branch:** Create or switch to `feat/sprint-10` before editing code.
Do not implement on `main` or `master`. Starting from `feat/sprint-10-design`
is acceptable only long enough to create this plan.

## Design Decisions Baked Into This Plan

1. `contract/profiles.py` is shared model code only. It is not exported as a
   standalone schema file.
2. `profiles: ["malformed-media"]` is a scenario-level opt-in. Missing opt-in
   is `E_PROFILE_REQUIRED` during validation, not a materializer error.
3. `corrupt_container_header` is an atomic timeline event and is version
   affecting.
4. The engine uses `EngineEventContext` so `resolved_seed` is available without
   adding more positional handler parameters.
5. The corruptor uses no RNG draws. Replacement bytes are hash-expanded from
   recorded seed material.
6. Probe failure after intentional corruption is success evidence:
   `probe_outcome="failed_expected"`.
7. `CorruptionActionError` maps to `outcome="corruption_failed"` and
   `stage="corruption"` in materialize, wall-clock run, and run replay.
8. Final materialize/run writers rebuild per-entity reports from the augmented
   manifest instead of persisting plan-time reports.
9. Existing `replay --against` remains strict same-toolchain comparison.
10. Cross-toolchain corruption comparison is a helper used by tests and docs,
    not a CLI mode.

## File Structure

### Create

```text
src/chaos_librarian/contract/profiles.py
  ProfileName, CorruptionProbeOutcome, CorruptionRecord.

src/chaos_librarian/engine/context.py
  EngineEventContext(run_id, scenario_id, resolved_seed).

src/chaos_librarian/materializer/corruption.py
  _CorruptionContext, apply_corruption_action, deterministic replacement bytes.

src/chaos_librarian/validation/rules/profile_opt_in.py
  rule_profile_opt_in for E_PROFILE_REQUIRED.

tests/materializer/test_corruption.py
tests/materializer/test_run_sprint10.py
tests/materializer/test_replay.py
tests/integration/test_materialize_sprint10_real.py
tests/cli/test_materialize_sprint10.py

tests/fixtures/scenarios/malformed-container-header.yaml
tests/fixtures/scenarios/invalid/corrupt-container-header-missing-profile.yaml
tests/fixtures/scenarios/invalid/corrupt-container-header-after-delete.yaml
tests/fixtures/scenarios/invalid/corrupt-container-header-during-slow-copy.yaml
```

### Modify

```text
src/chaos_librarian/contract/__init__.py
  SCENARIO_SCHEMA_VERSION 6 -> 7
  MANIFEST_SCHEMA_VERSION 4 -> 5
  MATERIALIZATION_SCHEMA_VERSION 5 -> 6
  ASSET_REPORT_SCHEMA_VERSION 4 -> 5

src/chaos_librarian/contract/scenario.py
  Add profiles, ProfileName, CORRUPT_CONTAINER_HEADER,
  CorruptContainerHeaderEvent(bytes: 1..4096), schema_version Literal[7].

src/chaos_librarian/contract/manifest.py
  ManifestVersion.corruption, Manifest.schema_version Literal[5].

src/chaos_librarian/contract/reports.py
  AssetSnapshot.corruption, AssetReport.schema_version Literal[5].

src/chaos_librarian/contract/materialization.py
  CorruptionAction, CorruptionProbeOutcome, corruption_actions,
  Outcome.CORRUPTION_FAILED, FailureStage.CORRUPTION,
  MaterializationReport.schema_version Literal[6].

src/chaos_librarian/contract/canonicalize.py
  Add corruption-evidence helper for cross-toolchain tests and docs.

src/chaos_librarian/engine/events.py
  EngineEventContext signature, corruption state-delta contract and handler.

src/chaos_librarian/engine/plan.py
src/chaos_librarian/engine/step.py
  Construct and pass EngineEventContext, preserving recorded resolved seed.

src/chaos_librarian/engine/reports.py
  Select greatest-index ManifestVersion for snapshots; include hashes, probes,
  corruption metadata.

src/chaos_librarian/engine/version_history.py
  Treat corrupt_container_header as version-affecting.

src/chaos_librarian/materializer/actions.py
src/chaos_librarian/materializer/preflight.py
  Add _CORRUPTION_ACTIONS and SUPPORTED_S10_ACTIONS.

src/chaos_librarian/materializer/errors.py
src/chaos_librarian/materializer/__init__.py
src/chaos_librarian/materializer/finalize.py
src/chaos_librarian/materializer/reports.py
src/chaos_librarian/materializer/run.py
src/chaos_librarian/materializer/wall_clock.py
src/chaos_librarian/materializer/replay.py
src/chaos_librarian/materializer/manifest_build.py
  Wire corruption dispatch, audit records, failure mapping, manifest
  augmentation, and regenerated reports.

src/chaos_librarian/cli/commands/replay.py
  Include normalized materialization corruption evidence in strict run replay
  comparison.
src/chaos_librarian/cli/commands/materialize.py
src/chaos_librarian/cli/commands/run.py
  Catch CorruptionActionError and emit the existing materialization error
  envelope with materialization_report_path.

src/chaos_librarian/validation/codes.py
src/chaos_librarian/validation/semantic.py
src/chaos_librarian/validation/rules/timeline_lifecycle.py
  Register profile gate and lifecycle checks.

tests/contract/*
tests/engine/*
tests/materializer/*
tests/validation/*
tests/cli/*
tests/fixtures/scenarios/*.yaml
tests/fixtures/scenarios/invalid/*.yaml
schemas/*.schema.json
docs/contract/schema-reference.md
docs/contract/fixture-layout.md
docs/contract/integration-recipes.md
docs/specs/chaos-librarian-design.md
```

## Task 1: Contract Models And Schema Bumps

**Files:**
- Create: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/manifest.py`
- Modify: `src/chaos_librarian/contract/reports.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`
- Modify: `tests/contract/test_manifest.py`
- Modify: `tests/contract/test_reports.py`
- Modify: `tests/contract/test_materialization.py`
- Modify: `tests/contract/test_schema_export.py`
- Modify: `tests/fixtures/scenarios/**/*.yaml`
- Modify: `schemas/*.schema.json`

- [ ] **Step 1: Write failing contract tests**

Add these tests using dictionary payloads and `Model.model_validate(payload)`
for negative cases:

- `test_scenario_accepts_malformed_media_profile`
- `test_scenario_rejects_unknown_profile_value`
- `test_corrupt_container_header_defaults_to_64_bytes`
- `test_corrupt_container_header_rejects_zero_bytes`
- `test_corrupt_container_header_rejects_4097_bytes`
- `test_manifest_version_round_trips_corruption_metadata`
- `test_asset_snapshot_round_trips_corruption_metadata`
- `test_corruption_probe_outcome_accepts_declared_values_only`
- `test_corruption_action_round_trips_hashes_and_probe_outcome`
- `test_corruption_action_rejects_bad_input_content_hash`
- `test_corruption_action_rejects_bad_output_content_hash`

Use this expected record shape in tests:

```python
{
    "profile": "malformed-media",
    "event_id": "corrupt_header_001",
    "corruptor": "container_header_v1",
    "byte_start": 0,
    "byte_count": 64,
    "seed_material": "container_header_v1:42:corrupt_header_001:asset_main",
}
```

- [ ] **Step 2: Verify tests fail before implementation**

Run:

```bash
uv run pytest tests/contract/test_scenario.py tests/contract/test_manifest.py \
  tests/contract/test_reports.py tests/contract/test_materialization.py -q
```

Expected: import or validation failures for missing profile/corruption models
and old schema versions.

- [ ] **Step 3: Add shared profile models**

Create `src/chaos_librarian/contract/profiles.py`:

```python
"""Shared profile and corruption metadata contract models."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict


class ProfileName(enum.StrEnum):
    MALFORMED_MEDIA = "malformed-media"


class CorruptionProbeOutcome(enum.StrEnum):
    FAILED_EXPECTED = "failed_expected"
    STILL_PROBEABLE = "still_probeable"


class CorruptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileName
    event_id: str
    corruptor: str
    byte_start: int
    byte_count: int
    seed_material: str
```

- [ ] **Step 4: Wire scenario profile and action contracts**

In `contract/scenario.py`, import `ProfileName`, add this enum member:

```python
CORRUPT_CONTAINER_HEADER = "corrupt_container_header"
```

Then add the event model:

```python
class CorruptContainerHeaderEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CORRUPT_CONTAINER_HEADER] = (
        TimelineActionName.CORRUPT_CONTAINER_HEADER
    )
    target: str
    bytes: int = Field(default=64, ge=1, le=4096)
```

Add `CorruptContainerHeaderEvent` to `TimelineEvent`, and add to `Scenario`:

```python
schema_version: Literal[7]
profiles: tuple[ProfileName, ...] = Field(default_factory=tuple)
```

- [ ] **Step 5: Wire manifest, reports, and materialization contracts**

In `contract/manifest.py`, import `CorruptionRecord`, add the version field,
and bump the manifest literal:

```python
from chaos_librarian.contract.profiles import CorruptionRecord

corruption: CorruptionRecord | None = None
schema_version: Literal[5]
```

In `contract/reports.py`, import `CorruptionRecord`, add the snapshot field,
and bump the asset-report literal:

```python
from chaos_librarian.contract.profiles import CorruptionRecord

corruption: CorruptionRecord | None = None
schema_version: Literal[5]
```

In `contract/materialization.py`, import `CorruptionProbeOutcome`, add the new
enum members, add `CorruptionAction`, and bump the report literal:

```python
from chaos_librarian.contract.profiles import CorruptionProbeOutcome

CORRUPTION_FAILED = "corruption_failed"
CORRUPTION = "corruption"


class CorruptionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: Literal[TimelineActionName.CORRUPT_CONTAINER_HEADER]
    target_asset_id: str
    input_path: str
    output_path: str
    input_version_id: str | None = None
    output_version_id: str
    input_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    output_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    corruptor: str
    byte_start: int
    byte_count: int
    seed_material: str
    probe_outcome: CorruptionProbeOutcome
    probe_error_tail: str | None = None
    duration_ns: int


class MaterializationReport(BaseModel):
    schema_version: Literal[6]
    corruption_actions: list[CorruptionAction] = Field(default_factory=list)
```

- [ ] **Step 6: Bump constants and all scenario fixtures**

In `contract/__init__.py`, update:

```python
SCENARIO_SCHEMA_VERSION: Final = 7
MANIFEST_SCHEMA_VERSION: Final = 5
MATERIALIZATION_SCHEMA_VERSION: Final = 6
ASSET_REPORT_SCHEMA_VERSION: Final = 5
```

Update every fixture that still has `schema_version: 6`:

```bash
rg -l '^schema_version: 6$' tests/fixtures/scenarios \
  | xargs perl -0pi -e 's/^schema_version: 6$/schema_version: 7/m'
```

- [ ] **Step 7: Regenerate schemas and run contract checks**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run pytest tests/contract/test_scenario.py tests/contract/test_manifest.py \
  tests/contract/test_reports.py tests/contract/test_materialization.py \
  tests/contract/test_contract_constants.py tests/contract/test_schema_export.py \
  tests/contract/test_sample_scenarios.py -q
uv run python -m chaos_librarian.schema_export --check
```

Expected: tests pass, schema check reports all schemas up to date, and no
`profiles.schema.json` file exists.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract tests/contract tests/fixtures/scenarios schemas
git commit -m "feat(contract): add malformed-media profile contracts"
```

## Task 2: Profile Validation, Lifecycle, And Preflight

**Files:**
- Create: `src/chaos_librarian/validation/rules/profile_opt_in.py`
- Modify: `src/chaos_librarian/validation/codes.py`
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `tests/validation/test_codes.py`
- Create: `tests/validation/rules/test_profile_opt_in.py`
- Modify: `tests/validation/rules/test_timeline_lifecycle.py`
- Modify: `tests/materializer/test_actions.py`
- Modify: `tests/materializer/test_preflight.py`
- Create: invalid fixture files listed in File Structure

- [ ] **Step 1: Write validation and preflight tests**

Add tests:

- `test_corruption_without_profile_emits_e_profile_required`
- `test_corruption_with_malformed_media_profile_passes_profile_rule`
- `test_corruption_after_delete_emits_lifecycle_invalid`
- `test_corruption_during_slow_copy_emits_lifecycle_invalid`
- `test_corruption_unknown_target_emits_e_target_unknown`
- `test_preflight_accepts_corrupt_container_header`
- `test_supported_s10_actions_includes_corruption_actions`

Add invalid fixtures with first-line expected markers:

```yaml
# expected: E_PROFILE_REQUIRED
schema_version: 7
scenario_id: corrupt-container-header-missing-profile
seed: 42
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
works:
  - id: work_001
    title: Broken Header
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: corrupt_header_001
    at: 1s
    action: corrupt_container_header
    target: asset_main
```

Use `# expected: E_LIFECYCLE_INVALID` for the after-delete and during-slow-copy
fixtures.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/validation/rules/test_profile_opt_in.py \
  tests/validation/rules/test_timeline_lifecycle.py \
  tests/materializer/test_actions.py tests/materializer/test_preflight.py -q
```

Expected: missing `E_PROFILE_REQUIRED`, missing rule module, and preflight
rejects `corrupt_container_header`.

- [ ] **Step 3: Add the profile-required validation rule**

In `validation/codes.py`:

```python
E_PROFILE_REQUIRED: Final = "E_PROFILE_REQUIRED"
```

Create `validation/rules/profile_opt_in.py`:

```python
"""Rule: corruption actions require the malformed-media profile."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PROFILE_REQUIRED
from chaos_librarian.validation.rules._common import Reporter, _iter_timeline_events

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def rule_profile_opt_in(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    reporter = Reporter(collector=collector, line_index=line_index)
    profiles_raw = raw.get("profiles", [])
    profiles = set(profiles_raw) if isinstance(profiles_raw, list) else set()
    if ProfileName.MALFORMED_MEDIA.value in profiles:
        return
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CORRUPT_CONTAINER_HEADER.value:
            continue
        event_id = event.get("id")
        suffix = f" for event {event_id!r}" if isinstance(event_id, str) else ""
        reporter.error(
            code=E_PROFILE_REQUIRED,
            message=(
                "corrupt_container_header requires profile "
                f"{ProfileName.MALFORMED_MEDIA.value!r}{suffix}"
            ),
            loc=("timeline", idx, "action"),
        )
```

Register `rule_profile_opt_in` in `validation/semantic.py` after
`rule_target_unknown` and before lifecycle simulation.

- [ ] **Step 4: Extend lifecycle and preflight action sets**

In `timeline_lifecycle.py`, add `TimelineActionName.CORRUPT_CONTAINER_HEADER`
to `_LOCATION_DEPENDENT_PASSTHROUGH` and `_PATH_MUTATING_PASSTHROUGH`.

In `materializer/actions.py`, add:

```python
_CORRUPTION_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {TimelineActionName.CORRUPT_CONTAINER_HEADER}
)

SUPPORTED_S10_ACTIONS: Final[frozenset[TimelineActionName]] = (
    _STDLIB_ACTIONS | _MEDIA_ACTIONS | _CORRUPTION_ACTIONS
)
```

In `materializer/preflight.py`, import and expose `SUPPORTED_S10_ACTIONS`, and
check timeline events against `SUPPORTED_S10_ACTIONS`.

- [ ] **Step 5: Run validation checks**

Run:

```bash
uv run pytest tests/validation/test_codes.py \
  tests/validation/rules/test_profile_opt_in.py \
  tests/validation/rules/test_timeline_lifecycle.py \
  tests/validation/test_invalid_corpus.py \
  tests/materializer/test_actions.py tests/materializer/test_preflight.py -q
uv run ruff check src/chaos_librarian/validation src/chaos_librarian/materializer \
  tests/validation tests/materializer
```

Expected: all tests pass and ruff prints no warnings.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/validation src/chaos_librarian/materializer/actions.py \
  src/chaos_librarian/materializer/preflight.py tests/validation tests/materializer \
  tests/fixtures/scenarios/invalid
git commit -m "feat(validation): require malformed-media profile"
```

## Task 3: Engine Event Context

**Files:**
- Create: `src/chaos_librarian/engine/context.py`
- Modify: `src/chaos_librarian/engine/events.py`
- Modify: `src/chaos_librarian/engine/plan.py`
- Modify: `src/chaos_librarian/engine/step.py`
- Modify: `tests/engine/conftest.py`
- Modify: `tests/engine/test_state_delta_contract.py`
- Modify: direct engine-event tests that call `apply_event`

- [ ] **Step 1: Write context signature lock tests**

Add a test in `tests/engine/test_state_delta_contract.py`:

```python
def test_apply_event_uses_engine_event_context_signature() -> None:
    import inspect

    from chaos_librarian.engine.events import apply_event

    assert list(inspect.signature(apply_event).parameters) == [
        "state",
        "resolved",
        "ids",
        "ctx",
    ]
```

- [ ] **Step 2: Verify the signature test fails**

Run:

```bash
uv run pytest \
  tests/engine/test_state_delta_contract.py::test_apply_event_uses_engine_event_context_signature \
  -q
```

Expected: failure showing the old `run_id, scenario_id` parameters.

- [ ] **Step 3: Add EngineEventContext**

Create `engine/context.py`:

```python
"""Engine event context shared by timeline handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineEventContext:
    run_id: uuid.UUID
    scenario_id: str
    resolved_seed: int
```

- [ ] **Step 4: Refactor event dispatch to use context**

In `engine/events.py`, change signatures:

```python
from chaos_librarian.engine.context import EngineEventContext


def apply_event(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    handler = _HANDLERS[resolved.event.action]
    return handler(state, resolved, ids, ctx)


_Handler = Callable[
    [WorldState, ResolvedEvent, IdAllocator, EngineEventContext],
    tuple[JournalEntry, ...],
]
```

Update `_new_atomic_entry` and every handler to use `ctx.run_id` and
`ctx.scenario_id`. Do not add a fifth positional handler parameter.

- [ ] **Step 5: Update plan and step call sites**

In `run_plan`, construct once after `run_id` is known:

```python
ctx = EngineEventContext(
    run_id=run_id,
    scenario_id=parsed.scenario_id,
    resolved_seed=resolved_seed,
)
```

Pass `ctx` to every `apply_event` call.

In `step_fixture`, construct from the replay bundle:

```python
ctx = EngineEventContext(
    run_id=bundle.run_id,
    scenario_id=scenario.scenario_id,
    resolved_seed=bundle.resolved_seed,
)
```

Pass the same context through `_recover_cursor` and the new-entry advance loop.

- [ ] **Step 6: Update tests and run engine checks**

Update test helpers to use:

```python
EngineEventContext(
    run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
    scenario_id="sc_test",
    resolved_seed=42,
)
```

Run:

```bash
uv run pytest tests/engine -q
uv run ruff check src/chaos_librarian/engine tests/engine
```

Expected: all engine tests pass and ruff prints no warnings.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine tests/engine
git commit -m "refactor(engine): pass event context to handlers"
```

## Task 4: Engine Corruption Semantics And Version History

**Files:**
- Modify: `src/chaos_librarian/engine/events.py`
- Modify: `src/chaos_librarian/engine/version_history.py`
- Modify: `tests/engine/conftest.py`
- Modify: `tests/engine/test_events_media.py`
- Modify: `tests/engine/test_plan.py`
- Modify: `tests/engine/test_step.py`
- Modify: `tests/engine/test_version_history.py`
- Modify: `tests/engine/test_state_delta_contract.py`

- [ ] **Step 1: Write failing engine tests**

Add tests:

- `test_corrupt_container_header_allocates_new_version_and_keeps_path`
- `test_corrupt_container_header_journal_records_corruption_metadata`
- `test_corrupt_container_header_uses_resolved_seed_in_seed_material`
- `test_seed_random_replay_preserves_corruption_seed_material`
- `test_step_recovery_regenerates_corruption_journal_byte_identically`
- `test_step_from_random_seed_bundle_uses_recorded_resolved_seed`
- `test_derive_version_history_includes_corruption_summary`

Expected journal `state_delta` keys:

```python
{
    "input_path",
    "output_path",
    "profile",
    "corruptor",
    "byte_start",
    "byte_count",
    "seed_material",
}
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/engine/test_events_media.py tests/engine/test_plan.py \
  tests/engine/test_step.py tests/engine/test_version_history.py \
  tests/engine/test_state_delta_contract.py -q
```

Expected: missing handler, missing state-delta contract, and missing version
history action.

- [ ] **Step 3: Implement the corruption handler**

In `engine/events.py`, import `CorruptionRecord`, `ProfileName`, and
`CorruptContainerHeaderEvent`. Add `_STATE_DELTA_KEYS`:

```python
TimelineActionName.CORRUPT_CONTAINER_HEADER: frozenset(
    {
        "input_path",
        "output_path",
        "profile",
        "corruptor",
        "byte_start",
        "byte_count",
        "seed_material",
    }
),
```

Add handler:

```python
def _handle_corrupt_container_header(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, CorruptContainerHeaderEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    corruptor = "container_header_v1"
    seed_material = f"{corruptor}:{ctx.resolved_seed}:{event.id}:{event.target}"
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        byte_start=0,
        byte_count=event.bytes,
        seed_material=seed_material,
    )
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id,
            asset_id=event.target,
            index=prior_version.index + 1,
            corruption=record,
        ),
    )
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.MALFORMED_MEDIA.value,
                "corruptor": corruptor,
                "byte_start": 0,
                "byte_count": event.bytes,
                "seed_material": seed_material,
            },
        ),
    )
```

Register it in `_HANDLERS`.

- [ ] **Step 4: Extend test action registry**

In `tests/engine/conftest.py`, import `CorruptContainerHeaderEvent`, add it to
`_TerminalEvent`, and add:

```python
TimelineActionName.CORRUPT_CONTAINER_HEADER: lambda: CorruptContainerHeaderEvent(
    id="ev",
    at="0ns",
    target="asset_hd_main",
    bytes=64,
),
```

- [ ] **Step 5: Extend version history**

In `engine/version_history.py`, add the action to `_VERSION_AFFECTING_ACTIONS`
and preserved keys:

```python
TimelineActionName.CORRUPT_CONTAINER_HEADER: frozenset(
    {"profile", "corruptor", "byte_start", "byte_count", "seed_material"}
),
```

- [ ] **Step 6: Run engine checks**

Run:

```bash
uv run pytest tests/engine/test_events_media.py tests/engine/test_plan.py \
  tests/engine/test_step.py tests/engine/test_version_history.py \
  tests/engine/test_state_delta_contract.py -q
uv run ruff check src/chaos_librarian/engine tests/engine
```

Expected: all listed tests pass and ruff prints no warnings.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine tests/engine
git commit -m "feat(engine): add deterministic corruption event"
```

## Task 5: Asset Reports And Regenerated Final Reports

**Files:**
- Modify: `src/chaos_librarian/engine/reports.py`
- Modify: `src/chaos_librarian/materializer/reports.py`
- Modify: `tests/engine/test_reports.py`
- Create: `tests/materializer/test_run_sprint10.py`

- [ ] **Step 1: Write report tests**

Add tests:

- `test_asset_snapshot_uses_current_greatest_index_version`
- `test_asset_snapshot_copies_hash_probe_and_corruption`
- `test_asset_report_json_emits_current_corruption_metadata`
- `test_materialize_reports_rebuild_from_augmented_manifest`

The first test must construct a manifest with two versions for one asset:
index `0` without corruption and index `1` with corruption. Assert that
`current.version_id`, `current.content_hash`, `current.probed`, and
`current.corruption` all come from index `1`.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/engine/test_reports.py tests/materializer/test_run_sprint10.py -q
```

Expected: `_snapshot_for` chooses the first version row and materializer report
builders still reuse plan-time reports.

- [ ] **Step 3: Fix snapshot selection**

In `engine/reports.py`, replace first-match version lookup with greatest index:

```python
def _current_version_for(asset_id: str, versions: list[ManifestVersion]) -> ManifestVersion | None:
    matches = [version for version in versions if version.asset_id == asset_id]
    if not matches:
        return None
    return max(matches, key=lambda version: version.index)
```

Use that helper in `_snapshot_for`, and populate:

```python
content_hash=version.content_hash,
probed=version.probed,
corruption=version.corruption,
```

- [ ] **Step 4: Rebuild reports from current artifacts**

In `materializer/reports.py`, change `build_reports` to call
`build_report_set` against the final manifests:

```python
def build_reports(plan_artifacts: PlanArtifacts) -> MaterializeReports:
    reports = build_report_set(
        initial=plan_artifacts.initial_manifest,
        current=plan_artifacts.current_manifest,
        journal=plan_artifacts.journal,
    )
    return MaterializeReports(
        assets={r.asset_id: r for r in reports.assets},
        works={r.work_id: r for r in reports.works},
        variants={r.variant_id: r for r in reports.variants},
        bundles={r.bundle_id: r for r in reports.bundles},
    )
```

- [ ] **Step 5: Run report checks**

Run:

```bash
uv run pytest tests/engine/test_reports.py tests/materializer/test_run_sprint10.py -q
uv run ruff check src/chaos_librarian/engine/reports.py \
  src/chaos_librarian/materializer/reports.py tests/engine/test_reports.py \
  tests/materializer/test_run_sprint10.py
```

Expected: tests pass and ruff prints no warnings.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/reports.py src/chaos_librarian/materializer/reports.py \
  tests/engine/test_reports.py tests/materializer/test_run_sprint10.py
git commit -m "fix(reports): rebuild reports from final manifests"
```

## Task 6: Materializer Corruption Dispatcher

**Files:**
- Create: `src/chaos_librarian/materializer/corruption.py`
- Modify: `src/chaos_librarian/materializer/errors.py`
- Modify: `src/chaos_librarian/materializer/__init__.py`
- Create: `tests/materializer/test_corruption.py`
- Modify: `tests/materializer/test_errors.py`

- [ ] **Step 1: Write corruption helper tests**

Add tests:

- `test_replacement_bytes_are_deterministic`
- `test_header_corruptor_changes_bytes_without_changing_length`
- `test_corruption_action_records_input_and_output_hashes`
- `test_probe_failure_records_failed_expected`
- `test_probe_success_records_still_probeable`
- `test_missing_input_raises_corruption_action_error`
- `test_short_file_raises_corruption_action_error`

Use a hand-built `AtomicJournalEntry` with `action="corrupt_container_header"`
and `state_delta` containing the keys from Task 4.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_corruption.py tests/materializer/test_errors.py -q
```

Expected: import failure for `materializer.corruption` and missing
`CorruptionActionError`.

- [ ] **Step 3: Add CorruptionActionError**

In `materializer/errors.py`:

```python
class CorruptionActionError(MaterializationError):
    error_code: str = "E_MATERIALIZE_CORRUPTION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        action: TimelineActionName,
        cause: BaseException,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload: dict[str, object] = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        super().__init__(message, asset_id=asset_id, field=field, payload=merged_payload)
        self.event_id = event_id
        self.cause = cause
        self.action = action
```

- [ ] **Step 4: Re-export the corruption error**

In `materializer/__init__.py`, add `CorruptionActionError` to the existing
multi-line `chaos_librarian.materializer.errors` import block and add
`"CorruptionActionError",` to the existing `__all__` list. This keeps CLI
command modules importing materializer exceptions from the package root.

- [ ] **Step 5: Implement corruption dispatcher**

Create `materializer/corruption.py` with:

```python
@dataclass(slots=True)
class _CorruptionContext:
    library_root: Path
    resolved_seed: int
    post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]] = field(
        default_factory=dict
    )
```

Implement `_replacement_bytes(seed_material: str, byte_count: int) -> bytes`
using:

```python
while len(output) < byte_count:
    block = hashlib.sha256(f"{seed_material}:{block_index}".encode("utf-8")).digest()
    output.extend(block)
    block_index += 1
return bytes(output[:byte_count])
```

Implement `apply_corruption_action(ctx, entry)`:

```python
input_path = ctx.library_root / str(entry.state_delta["input_path"])
output_path = ctx.library_root / str(entry.state_delta["output_path"])
byte_count = int(entry.state_delta["byte_count"])
seed_material = str(entry.state_delta["seed_material"])
```

Required behavior:

- Hash the input bytes before mutation.
- Reject missing files and files shorter than `byte_count`.
- Replace bytes `[0:byte_count]` using `_replacement_bytes`.
- Write through a sibling temp file, then `replace(output_path)`.
- Hash output bytes after mutation.
- Call `probe_file(output_path)`.
- Catch `ProbeParseError` and record
  `CorruptionProbeOutcome.FAILED_EXPECTED` with a short `probe_error_tail`.
- On probe success, record `CorruptionProbeOutcome.STILL_PROBEABLE` and stash
  the returned `ProbedMedia`.
- Store `ctx.post_phase_b_versions[output_version_id] = (output_hash, probed)`.
- Return `CorruptionAction`.
- Wrap read/write/hash/probe-shape failures in `CorruptionActionError`.

- [ ] **Step 6: Run corruption helper checks**

Run:

```bash
uv run pytest tests/materializer/test_corruption.py tests/materializer/test_errors.py -q
uv run ruff check src/chaos_librarian/materializer/corruption.py \
  src/chaos_librarian/materializer/errors.py tests/materializer/test_corruption.py
```

Expected: all tests pass and ruff prints no warnings.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/materializer/corruption.py \
  src/chaos_librarian/materializer/errors.py tests/materializer/test_corruption.py \
  src/chaos_librarian/materializer/__init__.py tests/materializer/test_errors.py
git commit -m "feat(materializer): add corruption dispatcher"
```

## Task 7: Batch Materialize Corruption Wiring

**Files:**
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/manifest_build.py`
- Modify: `src/chaos_librarian/materializer/reports.py`
- Modify: `src/chaos_librarian/materializer/finalize.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/cli/commands/materialize.py`
- Modify: `tests/materializer/test_run_sprint10.py`
- Create: `tests/cli/test_materialize_sprint10.py`

- [ ] **Step 1: Write batch materialize and CLI tests**

Add tests:

- `test_materialize_corruption_writes_manifest_and_report_metadata`
- `test_materialize_writes_one_corruption_action`
- `test_materialize_persisted_asset_report_matches_current_manifest`
- `test_corruption_failure_writes_corruption_failed_report`
- `test_cli_corruption_failure_exits_5_with_materialization_report_path`
- `test_cli_missing_profile_exits_3_and_creates_no_run_dir`

Patch phase-A synthesis in unit tests as existing Sprint 7 tests do. Patch
`apply_corruption_action` to return a `CorruptionAction` for success and raise
`CorruptionActionError` for failure.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_run_sprint10.py \
  tests/cli/test_materialize_sprint10.py -q
```

Expected: dispatcher never routes corruption actions and reports do not carry
`corruption_actions`.

- [ ] **Step 3: Add manifest augmentation helper for corruption**

In `manifest_build.py`, add:

```python
def augment_corrupted_versions(
    manifest: Manifest,
    post_phase_b_versions: Mapping[str, tuple[str, ProbedMedia | None]],
) -> None:
    augment_versions(manifest, post_phase_b_versions)
```

Use this wrapper from corruption wiring so the call site documents that the map
is corruption evidence. Keep `augment_versions` unchanged for media actions.

- [ ] **Step 4: Thread corruption_actions through reports and finalizers**

In `materializer/reports.py`, add a `corruption_actions` parameter to
`build_report` and pass it to `MaterializationReport`.

In `finalize.py`, add `corruption_actions` to `finalize_success`,
`finalize_failure`, and `finalize_failure_phase_b`. Map
`CorruptionActionError` to:

```python
stage = FailureStage.CORRUPTION
outcome = Outcome.CORRUPTION_FAILED
```

- [ ] **Step 5: Route corruption in batch materialize**

In `run.py`, create:

```python
corruption_actions: list[CorruptionAction] = []
corruption_ctx = _CorruptionContext(
    library_root=library_root,
    resolved_seed=resolved_seed,
)
```

During the journal walk:

```python
elif action in _CORRUPTION_ACTIONS:
    corruption_actions.append(apply_corruption_action(corruption_ctx, entry))
```

After phase B:

```python
augment_corrupted_versions(
    ctx.plan_artifacts.current_manifest,
    corruption_ctx.post_phase_b_versions,
)
```

Catch `CorruptionActionError` and finalize with `Outcome.CORRUPTION_FAILED`.

- [ ] **Step 6: Catch corruption failures in the materialize CLI**

In `cli/commands/materialize.py`, import `CorruptionActionError` from
`chaos_librarian.materializer` and add the same exit-5 envelope branch used for
filesystem and media phase-B failures:

```python
except CorruptionActionError as exc:
    emit_materialize_error(exc, json_output=json_output, run_dir=out)
    raise typer.Exit(code=5) from exc
```

The missing-profile CLI test must prove `ScenarioValidationError` still exits
`3` with `run_dir=None` and does not allocate the requested output directory.

- [ ] **Step 7: Run batch materialize checks**

Run:

```bash
uv run pytest tests/materializer/test_run_sprint10.py \
  tests/cli/test_materialize_sprint10.py -q
uv run ruff check src/chaos_librarian/materializer tests/materializer \
  tests/cli/test_materialize_sprint10.py
```

Expected: tests pass and ruff prints no warnings.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/materializer tests/materializer/test_run_sprint10.py \
  src/chaos_librarian/cli/commands/materialize.py tests/cli/test_materialize_sprint10.py
git commit -m "feat(materializer): route corruption actions"
```

## Task 8: Wall-Clock Run, Run Replay, And Replay Comparisons

**Files:**
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/cli/commands/run.py`
- Modify: `src/chaos_librarian/cli/commands/replay.py`
- Modify: `src/chaos_librarian/contract/canonicalize.py`
- Modify: `tests/materializer/test_wall_clock.py`
- Create: `tests/materializer/test_replay.py`
- Modify: `tests/cli/test_run.py`
- Modify: `tests/cli/test_replay.py`
- Modify: `tests/contract/test_canonicalize.py`

- [ ] **Step 1: Write wall-clock and replay tests**

Add tests:

- `test_run_applies_corruption_only_when_due`
- `test_run_omits_future_corruption_actions`
- `test_run_corruption_failure_maps_to_corruption_failed`
- `test_run_replay_reproduces_corruption_action_evidence`
- `test_run_replay_persists_regenerated_asset_reports`
- `test_run_replay_corruption_failure_writes_corruption_failed_report`
- `test_compare_run_replay_compares_materialization_corruption_fields`
- `test_compare_run_replay_ignores_corruption_duration_ns`
- `test_compare_run_replay_ignores_toolchain_and_invocation_volatility`
- `test_cross_toolchain_corruption_evidence_ignores_probe_and_hash_drift`
- `test_cli_run_corruption_failure_exits_5_with_materialization_report_path`

The strict `compare_run_replay` test must fail when only
`materialization.json.corruption_actions[0].probe_outcome` differs.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_wall_clock.py tests/materializer/test_replay.py \
  tests/cli/test_run.py tests/cli/test_replay.py tests/contract/test_canonicalize.py -q
```

Expected: corruption actions are not dispatched in run/replay, and strict replay
comparison ignores `materialization.json`.

- [ ] **Step 3: Wire wall-clock run**

In `_DispatchState`, add:

```python
corruption_ctx: _CorruptionContext
corruption_actions: list[CorruptionAction] = field(default_factory=list)
```

In `_make_dispatch_state`, construct `_CorruptionContext` with the run's
library root and recorded resolved seed.

In `_execute_entry`, route `_CORRUPTION_ACTIONS` to
`apply_corruption_action`. In `_final_artifacts_for_executed_prefix`, augment
corrupted versions before returning final artifacts.

In `_run_timed_phase`, catch `CorruptionActionError` together with existing
phase-B failures. In `_finalize_wall_clock_phase_b_failure` and
`_failure_record`, map `CorruptionActionError` to `Outcome.CORRUPTION_FAILED`
and `FailureStage.CORRUPTION`.

In `cli/commands/run.py`, import `CorruptionActionError` and add it to the
exit-5 materialization error tuple so wall-clock corruption failures preserve
the structured error envelope and `materialization_report_path`.

- [ ] **Step 4: Wire run replay**

In `materializer/replay.py`, create a local replay dispatch state before
entering the phase-B walk:

```python
@dataclass(slots=True)
class _RunReplayPhaseBState:
    fs_ctx: _PhaseBContext
    media_ctx: _MediaContext
    corruption_ctx: _CorruptionContext
    filesystem_actions: list[FilesystemAction] = field(default_factory=list)
    media_actions: list[MediaAction] = field(default_factory=list)
    corruption_actions: list[CorruptionAction] = field(default_factory=list)
```

Build this state in `_materialize_verified_run_prefix`, then pass it into
`_apply_prefix_phase_b(state, artifacts)`. If `CorruptionActionError` raises,
the caller still owns `state.filesystem_actions`, `state.media_actions`, and
`state.corruption_actions` for events completed before the failure.

Inside `_apply_prefix_phase_b`, route `_CORRUPTION_ACTIONS` to
`apply_corruption_action`, append returned records to
`state.corruption_actions`, augment corrupted versions from
`state.corruption_ctx.post_phase_b_versions`, and return normally on success.
After `_apply_prefix_phase_b` returns, `_materialize_verified_run_prefix`
passes `state.corruption_actions` to `build_report`.

On failure, write `materialization.json` with
`outcome=Outcome.CORRUPTION_FAILED`, one failure with
`stage=FailureStage.CORRUPTION`, the completed audit records from state, the
replay bundle, and a complete sentinel, then clean `library/` with
`cleanup_failed_phase_b_run` and re-raise. Do not leave a half-populated output
directory without `materialization.json`.

- [ ] **Step 5: Add strict materialization comparison**

In `cli/commands/replay.py`, have `compare_run_replay` compare
`materialization.json` with a normalizer:

```python
_CORRUPTION_COMPARE_FIELDS = (
    "event_id",
    "action",
    "target_asset_id",
    "input_path",
    "output_path",
    "input_version_id",
    "output_version_id",
    "input_content_hash",
    "output_content_hash",
    "corruptor",
    "byte_start",
    "byte_count",
    "seed_material",
    "probe_outcome",
    "probe_error_tail",
)


def _normalize_materialization_for_run_replay(data: dict[str, object]) -> dict[str, object]:
    return {
        "outcome": data.get("outcome"),
        "execution_mode": data.get("execution_mode"),
        "corruption_actions": [
            {field: action.get(field) for field in _CORRUPTION_COMPARE_FIELDS}
            for action in data.get("corruption_actions", [])
            if isinstance(action, dict)
        ],
    }
```

Call `_compare_json` for `materialization.json` using that normalizer. Keep
`library/` byte comparison strict. Do not compare materialization timestamps,
platform strings, toolchain versions, invocation records, wall-clock duration
metadata, or `corruption_actions[].duration_ns`.

- [ ] **Step 6: Add cross-toolchain corruption evidence helper**

In `contract/canonicalize.py`, add:

```python
def corruption_evidence(manifest: Manifest, report: MaterializationReport) -> dict[str, Any]:
    return {
        "manifest": canonicalize(manifest),
        "corruption_actions": [
            {
                "event_id": action.event_id,
                "target_asset_id": action.target_asset_id,
                "output_version_id": action.output_version_id,
                "corruptor": action.corruptor,
                "byte_start": action.byte_start,
                "byte_count": action.byte_count,
                "seed_material": action.seed_material,
            }
            for action in report.corruption_actions
        ],
    }
```

Do not call this helper from `replay --against`.

- [ ] **Step 7: Run run/replay checks**

Run:

```bash
uv run pytest tests/materializer/test_wall_clock.py tests/materializer/test_replay.py \
  tests/cli/test_run.py tests/cli/test_replay.py tests/contract/test_canonicalize.py -q
uv run ruff check src/chaos_librarian/materializer/wall_clock.py \
  src/chaos_librarian/materializer/replay.py src/chaos_librarian/cli/commands/replay.py \
  src/chaos_librarian/cli/commands/run.py src/chaos_librarian/contract/canonicalize.py \
  tests/materializer/test_wall_clock.py tests/materializer/test_replay.py \
  tests/cli/test_run.py tests/cli/test_replay.py tests/contract/test_canonicalize.py
```

Expected: tests pass and ruff prints no warnings.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/materializer/wall_clock.py \
  src/chaos_librarian/materializer/replay.py src/chaos_librarian/cli/commands/run.py \
  src/chaos_librarian/cli/commands/replay.py src/chaos_librarian/contract/canonicalize.py \
  tests/materializer/test_wall_clock.py tests/materializer/test_replay.py \
  tests/cli/test_run.py tests/cli/test_replay.py tests/contract/test_canonicalize.py
git commit -m "feat(run): replay corruption evidence"
```

## Task 9: Fixture, Integration Tests, And Contract Docs

**Files:**
- Create: `tests/fixtures/scenarios/malformed-container-header.yaml`
- Modify: `tests/contract/test_sample_scenarios.py`
- Create: `tests/integration/test_materialize_sprint10_real.py`
- Modify: `docs/specs/chaos-librarian-design.md`
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/contract/fixture-layout.md`
- Modify: `docs/contract/integration-recipes.md`

- [ ] **Step 1: Add the malformed-media fixture**

Create `tests/fixtures/scenarios/malformed-container-header.yaml`:

```yaml
schema_version: 7
scenario_id: malformed-container-header
seed: 110
duration_scale: short
profiles:
  - malformed-media
library:
  roots:
    - id: movies_hd
      path: movies-hd
works:
  - id: work_broken
    title: Broken Header
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 4
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
timeline:
  - id: corrupt_header_001
    at: 1s
    action: corrupt_container_header
    target: asset_main
    bytes: 64
```

- [ ] **Step 2: Write integration tests**

Add tests:

- `test_malformed_media_fixture_materializes_real_corruption`
- `test_malformed_media_fixture_replay_matches_same_toolchain`

Assert:

```python
assert report["outcome"] == "success"
assert len(report["corruption_actions"]) == 1
assert manifest["versions"][-1]["corruption"]["corruptor"] == "container_header_v1"
assert asset_report["current"]["corruption"]["event_id"] == "corrupt_header_001"
```

- [ ] **Step 3: Verify fixture and integration tests fail until wiring is complete**

Run:

```bash
uv run pytest tests/contract/test_sample_scenarios.py \
  tests/integration/test_materialize_sprint10_real.py -q
```

Expected before implementation is complete: fixture validation or materialize
failure. Expected after prior tasks: tests pass on hosts with ffmpeg and
ffprobe available.

- [ ] **Step 4: Update docs**

Update:

- `docs/specs/chaos-librarian-design.md`: state Sprint 10 implemented the
  explicit malformed-media corruption lane and deferred the rest to #70-#75.
- `docs/contract/schema-reference.md`: list scenario v7, manifest v5,
  materialization v6, and asset-report v5.
- `docs/contract/fixture-layout.md`: describe corrupted fixtures as normal run
  directories with labeled manifest/report evidence.
- `docs/contract/integration-recipes.md`: add a short malformed-media recipe
  with `materialize tests/fixtures/scenarios/malformed-container-header.yaml`.

Do not add voom-v2-specific expected policy language.

- [ ] **Step 5: Run docs and integration checks**

Run:

```bash
uv run pytest tests/contract/test_sample_scenarios.py \
  tests/integration/test_materialize_sprint10_real.py -q
uv run python -m chaos_librarian.schema_export --check
```

Expected: tests pass and schema check reports all schemas up to date. If the
host lacks ffmpeg or ffprobe, record the skipped integration reason in the final
handoff.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/scenarios tests/integration/test_materialize_sprint10_real.py \
  docs/specs/chaos-librarian-design.md docs/contract
git commit -m "docs: add malformed-media fixture guidance"
```

## Task 10: Final Verification

**Files:**
- All files touched by Tasks 1-9.

- [ ] **Step 1: Re-read the diff for unnecessary scope**

Run:

```bash
base_ref=${SPRINT10_BASE_REF:-feat/sprint-10-design}
git diff --stat "$base_ref"..HEAD
git diff "$base_ref"..HEAD -- \
  docs/superpowers/specs/2026-05-22-sprint-10-extended-profiles-foundation-design.md
```

Expected: the implementation did not edit the approved design spec except for
deliberate follow-up notes requested during review. If the spec changed, verify
the change is intentional before continuing.

- [ ] **Step 2: Run targeted test suite**

Run:

```bash
uv run pytest tests/contract tests/validation tests/engine tests/materializer \
  tests/cli/test_materialize_sprint10.py tests/cli/test_run.py tests/cli/test_replay.py \
  tests/integration/test_materialize_sprint10_real.py -q
```

Expected: all selected tests pass or real-ffmpeg integration tests skip only for
documented missing local tools.

- [ ] **Step 3: Run linters, type checker, and schema drift gate**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: every command exits `0` with no warnings.

- [ ] **Step 4: Run pre-commit hooks**

Run:

```bash
prek run --all-files
```

Expected: all hooks pass. If hooks modify files, inspect the diff, rerun the
affected tests, and amend with a new commit.

- [ ] **Step 5: Commit final verification fixes**

If verification required fixes, commit them:

```bash
git add .
git commit -m "chore: finish sprint 10 verification"
```

If verification required no fixes, leave the branch at the Task 9 commit.

## Self-Review Checklist

- Each in-scope spec item maps to a task:
  profile marker: Task 1 and Task 2.
  corruption action: Task 1 and Task 4.
  deterministic engine evidence: Task 3 and Task 4.
  materialized byte mutation: Task 6 and Task 7.
  materialize/run/replay wiring: Task 7 and Task 8.
  reports: Task 5, Task 7, and Task 8.
  fixtures and docs: Task 9.
  schema regeneration and verification: Task 1 and Task 10.
- No standalone profile schema is created.
- Deferred broad-profile requirements remain tracked by #70-#75.
- No new dependency is added.
