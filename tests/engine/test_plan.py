"""Tests for chaos_librarian.engine.plan."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    PlanOnlyReplayBundle,
)
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import PlanArtifacts, replay_plan_bundle, run_plan
from chaos_librarian.engine.plan import ReplayIntegrityError
from chaos_librarian.validation import RunInput, prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _input_and_report(name: str) -> tuple[RunInput, ValidationReport]:
    run_input = prepare_run_input(FIXTURE_DIR / name)
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
        assert artifacts.initial_manifest.schema_version == 1
        assert artifacts.current_manifest.schema_version == 1
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
