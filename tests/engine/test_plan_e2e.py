"""End-to-end plan tests: full CLI invocation, byte-identical regression."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.engine import PlanArtifacts, replay_plan_bundle
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.validation import prepare_replay_input_from_bytes

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"

_PACK_SCENARIOS = [
    "identity-move-rename.yaml",
    "version-evolution.yaml",
    "bundle-sidecars.yaml",
    "duplicate-variant.yaml",
    "slow-copy.yaml",
]


def _relative_files(root: Path) -> list[Path]:
    """All files under ``root`` as paths relative to ``root``, sorted."""
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def _replay_plan_bundle(bundle: PlanOnlyReplayBundle) -> PlanArtifacts:
    prepared_input = prepare_replay_input_from_bytes(
        scenario_bytes=bundle.scenario.encode("utf-8"),
        source_label=f"test-replay:{bundle.run_id}",
    )
    return replay_plan_bundle(bundle, prepared_input)


@pytest.mark.parametrize("scenario_name", _PACK_SCENARIOS)
def test_pack_scenario_plans_successfully(scenario_name: str, tmp_path: Path) -> None:
    """Every first-pack scenario (plus slow-copy fixture) plans end-to-end.

    WHY: Sprint 3 exit criterion — first scenario pack minus Active Library
    Churn executes successfully. ``slow-copy.yaml`` is included because the
    slow-copy multi-phase pair is the only V1 multi-phase mutation and must
    not regress.
    """
    out = tmp_path / "run"
    result = runner.invoke(app, ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(out)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (out / ".chaos-librarian-run").exists()
    assert (out / "replay.json").exists()


@pytest.mark.parametrize("scenario_name", _PACK_SCENARIOS)
def test_pack_scenario_bit_identical_across_runs(scenario_name: str, tmp_path: Path) -> None:
    """Two plan runs of the same scenario+seed produce byte-identical files.

    WHY: this proves same-input determinism. The replay round-trip below
    proves that ``replay.json`` is enough to reproduce the fixture. The two
    tests together pin the headline bit-identical guarantee from both ends:
    re-running the same input, and re-running from the bundle alone.
    """
    out_a = tmp_path / "run-a"
    out_b = tmp_path / "run-b"
    result_a = runner.invoke(app, ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(out_a)])
    result_b = runner.invoke(app, ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(out_b)])
    assert result_a.exit_code == 0, result_a.stdout + result_a.stderr
    assert result_b.exit_code == 0, result_b.stdout + result_b.stderr

    rel_a = _relative_files(out_a)
    rel_b = _relative_files(out_b)
    assert rel_a == rel_b
    for rel in rel_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes(), str(rel)


def test_replay_bundle_round_trip_matches_original(tmp_path: Path) -> None:
    """Replay from the bundle reproduces every artifact byte-for-byte.

    WHY: Sprint 3 exit criterion — replay of a plan-only bundle reproduces
    the same artifacts byte-for-byte. The earlier surrogate (two ``plan``
    invocations) only proved same-input determinism; this one exercises
    ``replay_plan_bundle`` so the bundle's structural completeness is what
    keeps the test green.
    """
    out_original = tmp_path / "run-original"
    out_replay = tmp_path / "run-replay"

    result = runner.invoke(
        app,
        [
            "plan",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(out_original),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    bundle = PlanOnlyReplayBundle.model_validate_json((out_original / "replay.json").read_text())
    replayed = _replay_plan_bundle(bundle)
    write_fixture(out_replay, replayed, bundle.scenario.encode("utf-8"))

    rel_original = _relative_files(out_original)
    rel_replay = _relative_files(out_replay)
    assert rel_original == rel_replay
    for rel in rel_original:
        assert (out_original / rel).read_bytes() == (out_replay / rel).read_bytes(), str(rel)


class TestStepVsPlanByteIdentical:
    """step from t=0 produces a journal identical to plan.

    WHY: headline exit criterion. Step mode and plan mode are equivalent
    constructions of the same fixture.
    """

    @pytest.mark.parametrize("scenario_name", _PACK_SCENARIOS)
    def test_step_and_plan_journals_match(self, scenario_name: str, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plan"
        step_dir = tmp_path / "step"
        assert (
            runner.invoke(
                app,
                ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(plan_dir)],
            ).exit_code
            == 0
        )
        assert (
            runner.invoke(
                app,
                ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(step_dir), "--steps", "0"],
            ).exit_code
            == 0
        )
        # Advance the empty fixture through every event
        for _ in range(20):  # generous cap; --next is idempotent at done
            result = runner.invoke(app, ["step", str(step_dir), "--next", "1", "--json"])
            payload = json.loads(result.stdout)
            if payload["done"]:
                break
        # Compare the two fixtures
        assert (plan_dir / "journal.jsonl").read_bytes() == (
            step_dir / "journal.jsonl"
        ).read_bytes()
        assert (plan_dir / "manifest.current.json").read_bytes() == (
            step_dir / "manifest.current.json"
        ).read_bytes()
        # replay.json must also be byte-identical: the stepped bundle's
        # execution_trace has to carry every alloc/rng entry the full plan
        # recorded, or replay against the stepped fixture byte-diffs.
        # Codex round 4 finding 1 — version-evolution and bundle-sidecars
        # in the pack scenarios are the load-bearing cases.
        assert (plan_dir / "replay.json").read_bytes() == (step_dir / "replay.json").read_bytes()
        for sub in (
            "assets",
            "movies",
            "series",
            "seasons",
            "episodes",
            "artists",
            "albums",
            "discs",
            "tracks",
            "variants",
            "bundles",
        ):
            plan_files = sorted((plan_dir / "reports" / sub).iterdir())
            step_files = sorted((step_dir / "reports" / sub).iterdir())
            assert [p.name for p in plan_files] == [p.name for p in step_files]
            for pf, sf in zip(plan_files, step_files, strict=True):
                assert pf.read_bytes() == sf.read_bytes(), pf.name


class TestPartialReplayRoundTripCLI:
    """A --steps K fixture replays byte-identical via the CLI.

    WHY: partial fixtures must be first-class — decision #12 / Codex
    finding 1.
    """

    @pytest.mark.parametrize(
        ("scenario_name", "k"),
        [
            ("identity-move-rename.yaml", 0),
            ("identity-move-rename.yaml", 1),
            ("identity-move-rename.yaml", 2),
            ("slow-copy.yaml", 0),
            ("slow-copy.yaml", 1),  # one step = entire pair
        ],
    )
    def test_partial_fixture_round_trip(self, scenario_name: str, k: int, tmp_path: Path) -> None:
        original = tmp_path / "original"
        replay_out = tmp_path / "replay"
        plan_args = [
            "plan",
            str(FIXTURE_DIR / scenario_name),
            "--out",
            str(original),
            "--steps",
            str(k),
        ]
        assert runner.invoke(app, plan_args).exit_code == 0
        result = runner.invoke(
            app,
            [
                "replay",
                str(original / "replay.json"),
                "--out",
                str(replay_out),
                "--against",
                str(original),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr


def test_seed_random_replay_round_trip_byte_identical(tmp_path: Path) -> None:
    """``seed: random`` scenarios replay byte-for-byte from the recorded bundle.

    WHY: a ``seed: random`` scenario draws a fresh seed at plan time, so
    two ``plan`` invocations of the same scenario would diverge. Replay
    must reuse the recorded ``resolved_seed`` to reproduce the original
    artifacts. This is the end-to-end proof for Codex adversarial-review
    finding 1; the unit-level equivalent lives in test_plan.py.
    """
    out_original = tmp_path / "run-original"
    out_replay = tmp_path / "run-replay"

    result = runner.invoke(
        app,
        [
            "plan",
            str(FIXTURE_DIR / "seed-random.yaml"),
            "--out",
            str(out_original),
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    bundle = PlanOnlyReplayBundle.model_validate_json((out_original / "replay.json").read_text())
    replayed = _replay_plan_bundle(bundle)
    write_fixture(out_replay, replayed, bundle.scenario.encode("utf-8"))

    rel_original = _relative_files(out_original)
    rel_replay = _relative_files(out_replay)
    assert rel_original == rel_replay
    for rel in rel_original:
        assert (out_original / rel).read_bytes() == (out_replay / rel).read_bytes(), str(rel)
