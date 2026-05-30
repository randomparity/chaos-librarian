"""Tests for chaos_librarian.engine.step.step_fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.engine import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    step_fixture,
)
from chaos_librarian.engine.plan import run_plan
from chaos_librarian.engine.writer import append_step, write_fixture
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.validation import (
    prepare_run_input,
    prepare_run_input_from_bytes,
    run_validation,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


def _make_fixture(tmp_path: Path, scenario_name: str, *, steps_limit: int | None = None) -> Path:
    run_input = prepare_run_input(FIXTURE_DIR / scenario_name)
    report = run_validation(run_input)
    artifacts = run_plan(
        run_input=run_input,
        validation_report=report,
        steps_limit=steps_limit,
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "run"
    write_fixture(out, artifacts, run_input.raw_bytes)
    return out


def _corruption_scenario_bytes(seed: str = "42") -> bytes:
    return f"""
schema_version: 30
scenario_id: corruption-step-test
seed: {seed}
duration_scale: short
profiles:
  - malformed-media
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_001
    title: Broken Header
    layout: movie_flat
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
series: []
artists: []
timeline:
  - id: corrupt_header_001
    at: 1s
    action: corrupt_container_header
    target: asset_main
    bytes: 64
""".lstrip().encode("utf-8")


def _make_inline_fixture(tmp_path: Path, scenario_bytes: bytes, *, steps_limit: int) -> Path:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label="inline-corruption-step",
    )
    report = run_validation(run_input)
    artifacts = run_plan(
        run_input=run_input,
        validation_report=report,
        steps_limit=steps_limit,
    )
    out = tmp_path / "run"
    write_fixture(out, artifacts, run_input.raw_bytes)
    return out


class TestStepFixtureHappyPath:
    """step_fixture from an empty-journal fixture matches a full plan run.

    WHY: this is the headline exit criterion — step mode and plan mode
    produce identical journals.
    """

    def test_step_from_zero_matches_full_plan(self, tmp_path: Path) -> None:
        # Start from a --steps 0 fixture (empty journal)
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        result = step_fixture(paused, n_steps=2)
        assert isinstance(result, StepResult)
        assert result.steps_applied == 2
        assert result.steps_remaining == 0
        assert result.done is True
        # Compare against a full plan
        full_input = prepare_run_input(FIXTURE_DIR / "identity-move-rename.yaml")
        full_report = run_validation(full_input)
        full = run_plan(run_input=full_input, validation_report=full_report)
        assert result.new_entries == full.journal

    def test_step_on_completed_fixture_returns_done(self, tmp_path: Path) -> None:
        full = _make_fixture(tmp_path, "identity-move-rename.yaml")
        result = step_fixture(full, n_steps=5)
        assert result.steps_applied == 0
        assert result.steps_remaining == 0
        assert result.done is True
        assert result.new_entries == ()

    def test_slow_copy_pair_counts_as_one_step(self, tmp_path: Path) -> None:
        # slow_copy_start + slow_copy_commit is ONE step unit; --next 1
        # advances both halves together (Codex round 3 finding 1).
        paused = _make_fixture(tmp_path, "slow-copy.yaml", steps_limit=0)
        result = step_fixture(paused, n_steps=1)
        assert result.steps_applied == 1  # step units
        assert len(result.new_entries) == 2  # raw entries
        assert result.new_entries[0].phase.value == "started"
        assert result.new_entries[1].phase.value == "committed"


class TestStepFixtureArgumentValidation:
    """step_fixture validates engine-level step counts before touching the run dir."""

    @pytest.mark.parametrize("n_steps", [0, -1])
    def test_requires_positive_step_count(self, tmp_path: Path, n_steps: int) -> None:
        with pytest.raises(ChaosLibrarianValueError, match="n_steps must be >= 1"):
            step_fixture(tmp_path / "missing-run-dir", n_steps=n_steps)


class TestStepFixtureSentinelChecks:
    """step_fixture refuses to operate without a valid sentinel.

    WHY: prevents accidentally treating a non-chaos-librarian directory
    as a fixture (re-use of a sentinel'd directory was deferred from
    Sprint 3; Sprint 4 owns it).
    """

    def test_missing_sentinel_raises(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        (fixture / ".chaos-librarian-run").unlink()
        with pytest.raises(SentinelInvalidError):
            step_fixture(fixture, n_steps=1)

    def test_malformed_sentinel_raises(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        (fixture / ".chaos-librarian-run").write_text("not json")
        with pytest.raises(SentinelInvalidError):
            step_fixture(fixture, n_steps=1)


class TestStepFixtureScenarioTampering:
    """Hand-editing scenario.yaml after fixture creation trips the integrity check.

    WHY: prevents step-mode replays from drifting from the bundle's
    recorded identity.
    """

    def test_modified_scenario_raises(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        scenario_path = fixture / "scenario.yaml"
        scenario_path.write_text(scenario_path.read_text() + "\n# hand-edited\n")
        with pytest.raises(ScenarioTamperedError):
            step_fixture(fixture, n_steps=1)


class TestStepFixtureJournalCorruption:
    """Cursor recovery rejects any mismatch between disk and regenerated journal.

    WHY: the second Codex finding — trusting len(existing_journal) lets
    hand-edited or duplicated journal lines slip through.
    """

    def test_corrupt_json_line(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=1)
        journal = fixture / "journal.jsonl"
        journal.write_text("{not json\n")
        with pytest.raises(JournalCorruptError) as excinfo:
            step_fixture(fixture, n_steps=1)
        assert excinfo.value.kind == "parse"

    def test_hand_edited_entry_action(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=1)
        journal = fixture / "journal.jsonl"
        line = journal.read_text().strip()
        entry = json.loads(line)
        entry["action"] = "delete_file"
        journal.write_text(json.dumps(entry) + "\n")
        with pytest.raises(JournalCorruptError) as excinfo:
            step_fixture(fixture, n_steps=1)
        assert excinfo.value.kind == "entry_mismatch"

    def test_duplicated_line_in_middle_trips_entry_mismatch(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=2)
        journal = fixture / "journal.jsonl"
        lines = journal.read_text().splitlines()
        # Duplicate the first line so the journal has three entries when only
        # two resolved events exist. Cursor recovery's entry-by-entry compare
        # trips entry_mismatch at the second slot (regenerated entry 2 vs the
        # duplicated copy of line[0]) before the length check can fire.
        journal.write_text(lines[0] + "\n" + lines[0] + "\n" + lines[1] + "\n")
        with pytest.raises(JournalCorruptError) as excinfo:
            step_fixture(fixture, n_steps=1)
        assert excinfo.value.kind == "entry_mismatch"

    def test_slow_copy_started_without_committed_off_boundary(self, tmp_path: Path) -> None:
        """A journal ending mid-pair is off-boundary.

        WHY: the slow_copy pair is one resolved event but two journal
        entries; truncating between them leaves the journal length
        equal to one even though no resolved event has completed.
        """
        # slow-copy.yaml: 1 slow_copy_start (1 entry) + 1 slow_copy_commit (1 entry).
        fixture = _make_fixture(tmp_path, "slow-copy.yaml", steps_limit=2)
        journal = fixture / "journal.jsonl"
        # Truncate the second resolved event's journal entry (the 'committed')
        # so the journal contains only the 'started' line.
        lines = journal.read_text().splitlines()
        journal.write_text(lines[0] + "\n")
        with pytest.raises(JournalCorruptError) as excinfo:
            step_fixture(fixture, n_steps=1)
        assert excinfo.value.kind == "off_boundary"


class TestStepFixtureFromEmpty:
    """Engine-level direct test for step_fixture on a --steps 0 fixture.

    WHY: Codex finding 2 — empty journal must be a happy-path cursor,
    not an off_boundary error. The documented initial-step workflow
    (plan --steps 0 then step --next 1) was blocked before this fix
    because _recover_cursor entered the first resolved event, called
    apply_event, then tripped the matched >= len(existing_journal)
    guard on the first regenerated entry.
    """

    def test_step_from_steps_zero_engine_level(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        result = step_fixture(paused, n_steps=1)
        assert result.steps_applied == 1
        assert result.new_replay_bundle.applied_events == 1


class TestStepFixtureTwice:
    """Two consecutive step calls from a --steps 0 fixture produce a
    full-run journal byte-equal to plan.

    WHY: Codex finding 1 — the previous fold-into-run_id design broke
    here because journal entries from step 1 carried a different run_id
    than the regenerated entries during step 2's cursor recovery. With
    the fold dropped, run_id is invariant and cursor recovery succeeds.
    """

    def test_step_twice_matches_plan(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        # Step 1 — advance one event, persist via append_step
        result1 = step_fixture(paused, n_steps=1)
        append_step(
            paused,
            new_entries=result1.new_entries,
            new_current_manifest=result1.new_current_manifest,
            new_report_set=result1.new_report_set,
            new_replay_bundle=result1.new_replay_bundle,
        )
        # Step 2 — must recover cursor cleanly, advance the second event
        result2 = step_fixture(paused, n_steps=1)
        assert result2.steps_applied == 1
        assert result2.done is True
        # Compare combined journal against a full plan run
        full = _make_fixture(tmp_path / "full", "identity-move-rename.yaml")
        combined = list(result1.new_entries) + list(result2.new_entries)
        full_entries = tuple(
            _JOURNAL_ADAPTER.validate_json(line)
            for line in (full / "journal.jsonl").read_text().splitlines()
        )
        assert tuple(combined) == full_entries


class TestStepFixtureRoundThree:
    """Round-3 regressions: step-unit semantics and journal_digest recompute.

    WHY: Codex round 3 findings 1 + 2. --next N counts step units; a
    slow_copy pair advances together. step_fixture also recomputes the
    journal_digest so the persisted bundle stays internally consistent
    after every advance.
    """

    def test_step_advances_slow_copy_pair_in_one_call(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "slow-copy.yaml", steps_limit=0)
        result = step_fixture(paused, n_steps=1)
        assert result.steps_applied == 1  # step units
        assert len(result.new_entries) == 2  # raw entries (start + commit)
        assert result.new_replay_bundle.applied_events == 2

    def test_step_recomputes_journal_digest(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        result = step_fixture(paused, n_steps=1)
        expected = hashlib.sha256(
            b"".join(
                entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n"
                for entry in result.new_entries
            )
        ).hexdigest()
        assert result.new_replay_bundle.journal_digest == expected


class TestStepFixtureRoundFour:
    """Round-4 regression: step_fixture preserves the full execution_trace.

    WHY: Codex round 4 finding 1. ID-allocating events (reencode_video,
    reencode_audio, add_file, create_sidecar) record AllocTraceEntry
    values during cursor recovery + advancement. Before the fix
    _finalize_step_result built the new bundle via model_copy(update=...)
    without execution_trace, so the on-disk replay.json carried the
    original (often empty) trace — making the stepped fixture
    byte-diff against a full plan and breaking replay.
    """

    def test_step_preserves_full_execution_trace(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path / "paused", "version-evolution.yaml", steps_limit=0)
        result = step_fixture(paused, n_steps=1)
        # reencode_video allocates a version id, so the trace must be non-empty
        assert len(result.new_replay_bundle.execution_trace) > 0
        # And must match what a full plan of the same prefix would produce
        full = _make_fixture(tmp_path / "full", "version-evolution.yaml", steps_limit=1)
        full_bundle = PlanOnlyReplayBundle.model_validate_json((full / "replay.json").read_text())
        assert result.new_replay_bundle.execution_trace == full_bundle.execution_trace


class TestStepFixtureCorruption:
    """Step recovery keeps corruption seed evidence stable."""

    def test_step_recovery_regenerates_corruption_journal_byte_identically(
        self, tmp_path: Path
    ) -> None:
        scenario_bytes = _corruption_scenario_bytes()
        paused = _make_inline_fixture(tmp_path, scenario_bytes, steps_limit=0)
        run_input = prepare_run_input_from_bytes(
            raw_bytes=scenario_bytes,
            source_label="inline-corruption-full",
        )
        full = run_plan(run_input=run_input, validation_report=run_validation(run_input))

        result = step_fixture(paused, n_steps=1)

        assert result.new_entries == full.journal

    def test_step_from_random_seed_bundle_uses_recorded_resolved_seed(self, tmp_path: Path) -> None:
        scenario_bytes = _corruption_scenario_bytes(seed="random")
        paused = _make_inline_fixture(tmp_path, scenario_bytes, steps_limit=0)
        bundle = PlanOnlyReplayBundle.model_validate_json((paused / "replay.json").read_text())

        result = step_fixture(paused, n_steps=1)

        entry = result.new_entries[0]
        assert entry.state_delta["seed_material"] == (
            f"container_header_v1:{bundle.resolved_seed}:corrupt_header_001:asset_main"
        )
