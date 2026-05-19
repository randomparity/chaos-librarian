"""End-to-end tests for the replay CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_full_fixture(tmp_path: Path, name: str = "identity-move-rename.yaml") -> Path:
    out = tmp_path / "run"
    runner.invoke(app, ["plan", str(FIXTURE_DIR / name), "--out", str(out)])
    return out


class TestReplayHappyPath:
    """replay reproduces a fixture from its bundle.

    WHY: Sprint 4 headline — replay round-trips byte-identical.
    """

    def test_replay_full_fixture(self, tmp_path: Path) -> None:
        fixture = _make_full_fixture(tmp_path)
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(fixture / "replay.json"), "--out", str(out), "--against", str(fixture)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_replay_partial_fixture(self, tmp_path: Path) -> None:
        partial = tmp_path / "partial"
        runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(partial),
                "--steps",
                "1",
            ],
        )
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(partial / "replay.json"), "--out", str(out), "--against", str(partial)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_replay_empty_journal_fixture(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(empty),
                "--steps",
                "0",
            ],
        )
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(empty / "replay.json"), "--out", str(out), "--against", str(empty)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr


class TestReplayIntegrityErrors:
    """Tampered bundles trip exit 6 with the integrity payload.

    WHY: integrity breaks must not silently produce divergent fixtures.
    """

    def test_tampered_scenario_field(self, tmp_path: Path) -> None:
        fixture = _make_full_fixture(tmp_path)
        bundle_path = fixture / "replay.json"
        payload = json.loads(bundle_path.read_text())
        payload["scenario"] = payload["scenario"] + "\n# tamper\n"
        bundle_path.write_text(json.dumps(payload))
        result = runner.invoke(app, ["replay", str(bundle_path), "--out", str(tmp_path / "out")])
        assert result.exit_code == 6

    def test_tampered_applied_events(self, tmp_path: Path) -> None:
        """Tampering applied_events trips exit 6 via journal_digest mismatch.

        WHY: two same-scenario+seed bundles share run_id, so the run_id
        check passes. Detection now falls to the digest check inside
        replay_plan_bundle: the recorded digest reflects the 1-event
        journal, but the recomputed digest after replaying 2 events
        won't match. Exit 6 even without --against.
        """
        partial = tmp_path / "partial"
        runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(partial),
                "--steps",
                "1",
            ],
        )
        bundle_path = partial / "replay.json"
        payload = json.loads(bundle_path.read_text())
        payload["applied_events"] = 2
        bundle_path.write_text(json.dumps(payload))
        result = runner.invoke(app, ["replay", str(bundle_path), "--out", str(tmp_path / "out")])
        assert result.exit_code == 6

    def test_replay_no_against_catches_applied_events_tamper(self, tmp_path: Path) -> None:
        """A bundle copied outside its fixture, with applied_events tampered, still
        trips exit 6 via journal_digest mismatch — no --against, no sentinel'd parent.

        WHY: Codex round 3 finding 2 — the integrity story must be
        self-contained, not dependent on having a comparison target.
        """
        partial = tmp_path / "partial"
        runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(partial),
                "--steps",
                "1",
            ],
        )
        bare = tmp_path / "bare"
        bare.mkdir()
        bundle_copy = bare / "replay.json"
        payload = json.loads((partial / "replay.json").read_text())
        payload["applied_events"] = 2
        bundle_copy.write_text(json.dumps(payload))
        out = tmp_path / "replay"
        result = runner.invoke(app, ["replay", str(bundle_copy), "--out", str(out)])
        assert result.exit_code == 6


class TestReplayArtifactDivergence:
    """If --against (or the auto-discovered original) diverges, exit 6.

    WHY: this is the second half of decision #3.
    """

    def test_against_divergent_fixture(self, tmp_path: Path) -> None:
        fixture = _make_full_fixture(tmp_path)
        journal = fixture / "journal.jsonl"
        journal.write_text(journal.read_text() + "\n# extra")
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(fixture / "replay.json"), "--out", str(out), "--against", str(fixture)],
        )
        assert result.exit_code == 6


class TestReplayOfSteppedFixture:
    """A fixture that has been advanced via step replays byte-identical against itself.

    WHY: Codex finding 1 — the previous fold-into-run_id design would have
    failed this test (the stepped fixture's replay.json.run_id would have
    encoded the new applied_events, but the journal still carried the
    original run_id). With the fold dropped, the stepped fixture is a
    valid replay source.
    """

    def test_replay_of_stepped_fixture_against_itself(self, tmp_path: Path) -> None:
        paused = tmp_path / "paused"
        runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(paused),
                "--steps",
                "0",
            ],
        )
        step_result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert step_result.exit_code == 0
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(paused / "replay.json"), "--out", str(out), "--against", str(paused)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    @pytest.mark.parametrize("scenario_name", ["version-evolution.yaml", "bundle-sidecars.yaml"])
    def test_replay_of_stepped_id_allocating_fixture(
        self, scenario_name: str, tmp_path: Path
    ) -> None:
        """A fixture advanced via step over ID-allocating events replays clean.

        WHY: Codex round 4 finding 1. step_fixture previously dropped
        the IdAllocator's TraceRecorder on the floor, so the persisted
        bundle's execution_trace was stale on any scenario that
        allocates a version/location/sidecar/mutation id at runtime.
        Replay regenerated the trace from scratch and byte-diffed
        against the on-disk replay.json.
        """
        paused = tmp_path / "paused"
        assert (
            runner.invoke(
                app,
                [
                    "plan",
                    str(FIXTURE_DIR / scenario_name),
                    "--out",
                    str(paused),
                    "--steps",
                    "0",
                ],
            ).exit_code
            == 0
        )
        for _ in range(20):
            step_result = runner.invoke(app, ["step", str(paused), "--next", "1", "--json"])
            assert step_result.exit_code == 0, step_result.stdout + step_result.stderr
            if json.loads(step_result.stdout)["done"]:
                break
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(paused / "replay.json"), "--out", str(out), "--against", str(paused)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr


def test_replay_refuses_materialize_bundle(tmp_path: Path) -> None:
    """WHY: Sprint 5 ships the MaterializeReplayBundle variant for schema
    stability but does NOT implement materialize replay. The CLI must
    refuse with exit 1 and a structured payload so agents know to expect
    this in Sprint 9, not silently parse it as plan-only."""
    bundle_path = tmp_path / "replay.json"
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "chaos_librarian_version": "0.1.0",
                "scenario": "schema_version: 2\nscenario_id: x\n",
                "run_id": "00000000-0000-4000-8000-000000000001",
                "resolved_seed": 1,
                "applied_events": 0,
                "journal_digest": "0" * 64,
                "execution_trace": [],
                "execution_mode": "materialize",
                "created_at": "2026-05-18T00:00:00Z",
                "toolchain": {"ffmpeg": "7.1.1"},
            }
        )
    )
    out = tmp_path / "out"
    result = runner.invoke(app, ["replay", str(bundle_path), "--out", str(out), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["error"] == "materialize_replay_not_implemented"
    assert payload["execution_mode"] == "materialize"
