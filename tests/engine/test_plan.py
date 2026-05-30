"""Tests for chaos_librarian.engine.plan."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    PlanOnlyReplayBundle,
)
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import (
    PlanArtifacts,
    ReplayIntegrityError,
    replay_plan_bundle,
    run_materializer_plan,
    run_plan,
)
from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.validation import (
    RunInput,
    prepare_run_input,
    prepare_run_input_from_bytes,
    run_validation,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _input_and_report(name: str) -> tuple[RunInput, ValidationReport]:
    run_input = prepare_run_input(FIXTURE_DIR / name)
    return run_input, run_validation(run_input)


def _corruption_input_and_report(seed: str = "42") -> tuple[RunInput, ValidationReport]:
    scenario = f"""
schema_version: 30
scenario_id: corruption-plan-test
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
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline:
  - id: corrupt_header_001
    at: 1s
    action: corrupt_container_header
    target: asset_main
    bytes: 64
""".lstrip()
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario.encode("utf-8"),
        source_label="inline-corruption-plan",
    )
    return run_input, run_validation(run_input)


class TestRunPlanBasics:
    """run_plan returns a PlanArtifacts with all six artifacts populated.

    WHY: every artifact field is part of the public contract; missing one
    means the fixture write step has no source for that file.
    """

    def test_returns_plan_artifacts(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        assert isinstance(artifacts, PlanArtifacts)
        assert artifacts.initial_manifest.schema_version == MANIFEST_SCHEMA_VERSION
        assert artifacts.current_manifest.schema_version == MANIFEST_SCHEMA_VERSION
        assert len(artifacts.journal) == 2  # move + rename
        assert isinstance(artifacts.replay_bundle, PlanOnlyReplayBundle)
        assert artifacts.replay_bundle.execution_mode == ExecutionMode.PLAN_ONLY
        assert artifacts.replay_bundle.resolved_seed == 42
        assert artifacts.validation_report.ok is True
        assert artifacts.sentinel.created_at is None


class TestRunPlanDeterminism:
    """run_plan is deterministic for a fixed (scenario, seed).

    WHY: this is Sprint 3's headline exit criterion — plan-only output is
    bit-identical for a fixed seed across runs.
    """

    def test_two_runs_produce_equal_artifacts(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        a = run_plan(run_input=run_input, validation_report=report)
        b = run_plan(run_input=run_input, validation_report=report)
        assert a.initial_manifest == b.initial_manifest
        assert a.current_manifest == b.current_manifest
        assert a.journal == b.journal
        assert a.replay_bundle == b.replay_bundle
        assert a.sentinel == b.sentinel

    def test_run_id_is_plan_only_uuid5(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        a = run_plan(run_input=run_input, validation_report=report)
        assert a.replay_bundle.run_id.version == 5


class TestRunMaterializerPlan:
    """run_materializer_plan can serve materializer-owned raw journal prefixes.

    WHY: wall-clock finalization needs exact executed event counts and a
    materialized UUID4 run_id, while plan-only replay must keep its existing
    step-boundary semantics.
    """

    def test_accepts_run_id_override(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        run_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
        artifacts = run_materializer_plan(
            run_input=run_input,
            validation_report=report,
            run_id_override=run_id,
        )
        assert artifacts.replay_bundle.run_id == run_id
        assert {entry.run_id for entry in artifacts.journal} == {run_id}

    def test_raw_prefix_applies_one_event(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_materializer_plan(
            run_input=run_input,
            validation_report=report,
            applied_events_override=1,
        )
        assert artifacts.replay_bundle.applied_events == 1
        assert [entry.event_id for entry in artifacts.journal] == ["move_001"]

    def test_rejects_steps_and_raw_prefix_together(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        with pytest.raises(ChaosLibrarianError, match="mutually exclusive"):
            run_materializer_plan(
                run_input=run_input,
                validation_report=report,
                steps_limit=1,
                applied_events_override=1,
            )

    def test_rejects_negative_raw_prefix(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        with pytest.raises(ChaosLibrarianError, match="applied_events_override must be >= 0"):
            run_materializer_plan(
                run_input=run_input,
                validation_report=report,
                applied_events_override=-1,
            )

    def test_rejects_raw_prefix_past_timeline(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        with pytest.raises(ChaosLibrarianError, match="applied_events_override exceeds timeline"):
            run_materializer_plan(
                run_input=run_input,
                validation_report=report,
                applied_events_override=999,
            )


class TestRunPlanFirstPack:
    """Every first-pack scenario (minus Active Library Churn) runs to completion.

    WHY: this is Sprint 3's exit criterion: the four first-pack scenarios
    execute end-to-end. Sprint 8 adds Active Library Churn.
    """

    @staticmethod
    def _names() -> list[str]:
        return [
            "identity-move-rename.yaml",
            "version-evolution.yaml",
            "bundle-sidecars.yaml",
            "duplicate-variant.yaml",
        ]

    def test_each_pack_scenario_runs(self) -> None:
        for name in self._names():
            run_input, report = _input_and_report(name)
            artifacts = run_plan(run_input=run_input, validation_report=report)
            assert artifacts.replay_bundle.run_id is not None, name


class TestReplayPlanBundle:
    """``replay_plan_bundle`` reproduces an in-memory PlanArtifacts from a bundle.

    WHY: Sprint 3 exit criterion — replay of a plan-only bundle reproduces
    the same artifacts byte-for-byte. The end-to-end byte check lives in
    Task 13; this unit test pins the in-memory contract.
    """

    def test_replay_returns_equivalent_artifacts(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.replay_bundle == original.replay_bundle
        assert replayed.initial_manifest == original.initial_manifest
        assert replayed.current_manifest == original.current_manifest
        assert replayed.journal == original.journal

    def test_replay_uses_recorded_seed_for_seed_random(self) -> None:
        """``replay_plan_bundle`` reuses ``bundle.resolved_seed`` instead of redrawing.

        WHY: ``seed: random`` scenarios produce a fresh integer at plan time.
        Without an override, replay would draw a different seed and diverge —
        ``run_id``, sentinel, replay.json, and trace would no longer match
        the recorded artifacts. This is Codex adversarial-review finding 1.
        """
        run_input, report = _input_and_report("seed-random.yaml")
        assert report.ok, [i.code for i in report.issues]
        original = run_plan(run_input=run_input, validation_report=report)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.replay_bundle.resolved_seed == original.replay_bundle.resolved_seed
        assert replayed.replay_bundle.run_id == original.replay_bundle.run_id
        assert replayed.replay_bundle == original.replay_bundle
        assert replayed.journal == original.journal

    def test_seed_random_replay_preserves_corruption_seed_material(self) -> None:
        run_input, report = _corruption_input_and_report(seed="random")
        assert report.ok, [i.code for i in report.issues]
        original = run_plan(run_input=run_input, validation_report=report)
        replayed = replay_plan_bundle(original.replay_bundle)

        original_entry = original.journal[0]
        replayed_entry = replayed.journal[0]

        assert original_entry.state_delta["seed_material"] == (
            f"container_header_v1:{original.replay_bundle.resolved_seed}:"
            "corrupt_header_001:asset_main"
        )
        assert replayed_entry.state_delta == original_entry.state_delta

    def test_replay_raises_on_run_id_mismatch(self) -> None:
        """Tampered bundles raise ``ReplayIntegrityError`` instead of silently diverging.

        WHY: if ``bundle.resolved_seed`` is mutated but ``bundle.run_id`` is
        left intact, the recomputed run_id (from content_hash + override seed)
        no longer agrees with the recorded one. Raising surfaces the
        corruption before producing artifacts that look authoritative but
        cannot be matched to the original run.
        """
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report)
        tampered = original.replay_bundle.model_copy(
            update={"resolved_seed": original.replay_bundle.resolved_seed + 1}
        )
        with pytest.raises(ReplayIntegrityError) as exc_info:
            replay_plan_bundle(tampered)
        message = str(exc_info.value)
        assert str(tampered.run_id) in message
        # The recomputed run_id must also be in the message so operators can
        # see which side of the mismatch came from the recorded bundle vs.
        # the recomputed value.
        assert "recomputed" in message.lower() or "computed" in message.lower()


class TestRunPlanStepsLimit:
    """run_plan stops at steps_limit and binds applied_events accordingly.

    WHY: partial fixtures are first-class artifacts (decision #12). Their
    identity is bound to scenario+seed via run_id; the prefix length is
    recorded separately in applied_events so two truncation points of
    the same run share a run_id.
    """

    def test_zero_steps_yields_empty_journal(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=0)
        assert artifacts.journal == ()
        assert artifacts.replay_bundle.applied_events == 0
        assert artifacts.replay_bundle.journal_digest == hashlib.sha256(b"").hexdigest()
        # Same scenario+seed → same run_id, even though applied_events differ.
        full = run_plan(run_input=run_input, validation_report=report)
        assert full.replay_bundle.applied_events == 2
        assert full.replay_bundle.run_id == artifacts.replay_bundle.run_id

    def test_partial_run_shared_run_id(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        one = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        two = run_plan(run_input=run_input, validation_report=report, steps_limit=2)
        assert one.replay_bundle.applied_events == 1
        assert two.replay_bundle.applied_events == 2
        assert one.replay_bundle.run_id == two.replay_bundle.run_id
        assert len(one.journal) == 1
        assert len(two.journal) == 2
        # slow-copy: one step unit covers two raw events → boundaries = [2]
        sc_input, sc_report = _input_and_report("slow-copy.yaml")
        sc_one = run_plan(run_input=sc_input, validation_report=sc_report, steps_limit=1)
        assert sc_one.replay_bundle.applied_events == 2
        assert len(sc_one.journal) == 2

    def test_steps_limit_exceeds_timeline_clamps(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=99)
        assert artifacts.replay_bundle.applied_events == 2  # clamped
        full = run_plan(run_input=run_input, validation_report=report)
        assert artifacts.replay_bundle.run_id == full.replay_bundle.run_id

    def test_none_yields_full_run(self) -> None:
        """steps_limit=None is equivalent to len(timeline) for applied_events."""
        run_input, report = _input_and_report("identity-move-rename.yaml")
        none_run = run_plan(run_input=run_input, validation_report=report, steps_limit=None)
        full = run_plan(run_input=run_input, validation_report=report, steps_limit=2)
        assert none_run.replay_bundle.run_id == full.replay_bundle.run_id
        assert none_run.replay_bundle.applied_events == 2


class TestRunPlanSlowCopyBoundary:
    """--steps 1 on slow-copy.yaml applies BOTH start AND commit.

    WHY: Codex round 3 finding 1 — a step unit is user-visible, not
    journal-entry-shaped. One step on a slow_copy pair advances both
    halves together; the engine must never produce an off-boundary
    fixture.
    """

    def test_slow_copy_one_step_applies_both_halves(self) -> None:
        run_input, report = _input_and_report("slow-copy.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        assert artifacts.replay_bundle.applied_events == 2
        assert len(artifacts.journal) == 2
        # Ordering: started then committed
        assert artifacts.journal[0].phase.value == "started"
        assert artifacts.journal[1].phase.value == "committed"


class TestReplayPartialBundles:
    """replay_plan_bundle reproduces partial fixtures.

    WHY: decision #12 of the design — partial fixtures are first-class.
    The integrity checks fire on scenario / resolved_seed tampering,
    applied_events off-boundary, and journal_digest mismatch.
    """

    def test_replay_zero_step_bundle(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=0)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.replay_bundle.run_id == original.replay_bundle.run_id
        assert replayed.replay_bundle.applied_events == 0
        assert replayed.journal == ()

    def test_replay_partial_bundle_round_trip(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.journal == original.journal
        assert replayed.replay_bundle.run_id == original.replay_bundle.run_id

    def test_replay_mid_pair_tamper_trips_integrity(self) -> None:
        """Tampering applied_events to an off-boundary value trips integrity.

        WHY: Codex round 3 finding 1 — partial fixtures must land on a
        step-unit boundary; mid-pair counts are nonsensical.
        """
        run_input, report = _input_and_report("slow-copy.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        # boundaries == [2]; flip applied_events from 2 to 1 (mid-pair)
        tampered = original.replay_bundle.model_copy(update={"applied_events": 1})
        with pytest.raises(ReplayIntegrityError, match="step boundary"):
            replay_plan_bundle(tampered)

    def test_replay_journal_digest_mismatch_trips_integrity(self) -> None:
        """Tampering journal_digest directly trips integrity.

        WHY: Codex round 3 finding 2 — digest is the self-contained integrity
        anchor.
        """
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        bogus = "0" * 64
        tampered = original.replay_bundle.model_copy(update={"journal_digest": bogus})
        with pytest.raises(ReplayIntegrityError, match="journal_digest"):
            replay_plan_bundle(tampered)

    def test_replay_applied_events_tampered_to_valid_boundary_trips_digest(self) -> None:
        """applied_events flipped between two valid boundaries is caught by digest.

        WHY: Codex round 3 finding 2 — without journal_digest, flipping
        applied_events from 1 to 2 (both valid on identity-move-rename) would
        silently produce a longer fixture. The recorded digest reflects the
        1-event journal, so the recomputed 2-event digest must mismatch.
        """
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        # boundaries == [1, 2]; both are valid. Flip applied_events but leave digest.
        tampered = original.replay_bundle.model_copy(update={"applied_events": 2})
        with pytest.raises(ReplayIntegrityError, match="journal_digest"):
            replay_plan_bundle(tampered)
