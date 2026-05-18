"""End-to-end plan tests: full CLI invocation, byte-identical regression."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.engine import replay_plan_bundle
from chaos_librarian.engine.writer import write_fixture

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"

_PACK_SCENARIOS = [
    "identity-move-rename.yaml",
    "version-evolution.yaml",
    "bundle-sidecars.yaml",
    "duplicate-variant.yaml",
    "slow-copy.yaml",
]


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

    file_names = sorted(p.name for p in out_a.iterdir())
    assert file_names == sorted(p.name for p in out_b.iterdir())
    for name in file_names:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


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
    replayed = replay_plan_bundle(bundle)
    write_fixture(out_replay, replayed, bundle.scenario.encode("utf-8"))

    for name in [
        ".chaos-librarian-run",
        "manifest.current.json",
        "manifest.initial.json",
        "replay.json",
        "scenario.yaml",
        "validation.json",
        "journal.jsonl",
    ]:
        assert (out_original / name).read_bytes() == (out_replay / name).read_bytes(), name


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
    replayed = replay_plan_bundle(bundle)
    write_fixture(out_replay, replayed, bundle.scenario.encode("utf-8"))

    for name in [
        ".chaos-librarian-run",
        "manifest.current.json",
        "manifest.initial.json",
        "replay.json",
        "scenario.yaml",
        "validation.json",
        "journal.jsonl",
    ]:
        assert (out_original / name).read_bytes() == (out_replay / name).read_bytes(), name
