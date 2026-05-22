"""End-to-end tests for the replay CLI command."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli._envelope import E_REPLAY_DIVERGENCE
from chaos_librarian.cli.app import app
from chaos_librarian.cli.commands import replay as replay_cmd
from chaos_librarian.contract import REPLAY_BUNDLE_SCHEMA_VERSION, RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import (
    MaterializedAsset,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import SENTINEL_FILENAME, RunSentinel, RunSentinelState
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine import compare_run_replay, run_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.writer import canonical_json
from chaos_librarian.materializer import replay as replay_mod
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.validation import prepare_run_input, run_validation

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _make_full_fixture(tmp_path: Path, name: str = "identity-move-rename.yaml") -> Path:
    out = tmp_path / "run"
    runner.invoke(app, ["plan", str(FIXTURE_DIR / name), "--out", str(out)])
    return out


def _make_wall_clock_fixture(
    tmp_path: Path,
    *,
    scenario_name: str = "identity-move-rename.yaml",
    applied_events: int = 1,
) -> Path:
    scenario_path = FIXTURE_DIR / scenario_name
    run_input = prepare_run_input(scenario_path)
    report = run_validation(run_input)
    safe_count = applied_events
    if applied_events > len(resolve_timeline(run_input.scenario)):
        safe_count = 0
    artifacts = run_plan(
        run_input=run_input,
        validation_report=report,
        run_id_override=RUN_ID,
        applied_events_override=safe_count,
    )
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in artifacts.journal
    ]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    bundle = MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario=run_input.raw_bytes.decode("utf-8"),
        run_id=RUN_ID,
        resolved_seed=artifacts.replay_bundle.resolved_seed,
        applied_events=applied_events,
        journal_digest=digest,
        execution_mode=ExecutionMode.RUN,
        created_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "library").mkdir()
    (run_dir / "replay.json").write_text(canonical_json(bundle), encoding="utf-8")
    (run_dir / "journal.jsonl").write_bytes(serialize_journal_bytes(artifacts.journal))
    (run_dir / "manifest.initial.json").write_text(
        canonical_json(artifacts.initial_manifest), encoding="utf-8"
    )
    (run_dir / "manifest.current.json").write_text(
        canonical_json(artifacts.current_manifest), encoding="utf-8"
    )
    (run_dir / "validation.json").write_text(canonical_json(report), encoding="utf-8")
    (run_dir / SENTINEL_FILENAME).write_text(
        canonical_json(
            RunSentinel(
                run_id=RUN_ID,
                schema_version=RUN_SENTINEL_SCHEMA_VERSION,
                created_by="chaos-librarian-test",
                created_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
                state=RunSentinelState.COMPLETE,
            )
        ),
        encoding="utf-8",
    )
    return run_dir


def _patch_run_replay_materializer(monkeypatch: pytest.MonkeyPatch) -> None:
    caps = Capabilities(
        schema_version=1,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
        ),
    )
    monkeypatch.setattr(replay_mod, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(replay_mod, "assert_capable_for_static_materialize", lambda _caps: None)
    monkeypatch.setattr(replay_mod, "materialize_one_asset", _fake_materialize_one_asset)


def _fake_materialize_one_asset(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    root_path: str,
    skip_languages=frozenset(),
):
    del resolved_seed, caps, skip_languages
    data = f"{asset.id}-bytes".encode()
    path = out_dir / "library" / root_path / f"{asset.id}.{asset.container}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return (
        ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", str(path)],
            exit_code=0,
            duration_ns=1,
        ),
        MaterializedAsset(
            asset_id=asset.id,
            location_path=str(Path("library") / root_path / f"{asset.id}.{asset.container}"),
            content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        ProbedMedia(
            container=asset.container,
            duration_seconds=asset.duration_seconds,
            size_bytes=len(data),
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
        ),
        {},
    )


def _make_materialized_run_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    _patch_run_replay_materializer(monkeypatch)
    source_bundle = _make_wall_clock_fixture(tmp_path, applied_events=1)
    source = tmp_path / "source"
    first_replay = runner.invoke(
        app,
        ["replay", str(source_bundle / "replay.json"), "--out", str(source)],
    )
    assert first_replay.exit_code == 0, first_replay.stdout + first_replay.stderr
    return source


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


class TestReplayRunBundles:
    """Run-mode bundles replay by outcome, not byte-for-byte timing."""

    def test_replay_accepts_run_bundle(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _patch_run_replay_materializer(monkeypatch)
        run_dir = _make_wall_clock_fixture(tmp_path, applied_events=1)
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(run_dir / "replay.json"), "--out", str(out), "--json"],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        source_payload = json.loads((run_dir / "replay.json").read_text())
        assert payload["run_id"] == source_payload["run_id"]
        assert payload["compared_against"] is None
        assert (out / "replay.json").exists()
        assert (out / "journal.jsonl").exists()
        assert (out / "manifest.current.json").exists()
        replay_payload = json.loads((out / "replay.json").read_text())
        assert replay_payload["execution_mode"] == "run"

    def test_replay_run_bundle_compares_against_normalized_output(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _make_materialized_run_fixture(monkeypatch, tmp_path)
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            [
                "replay",
                str(source / "replay.json"),
                "--out",
                str(out),
                "--against",
                str(source),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["compared_against"] == str(source)

    def test_replay_run_bundle_against_catches_library_divergence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        source = _make_materialized_run_fixture(monkeypatch, tmp_path)
        (source / "library" / "movies-hd" / "moved.mkv").write_bytes(b"tampered")
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            [
                "replay",
                str(source / "replay.json"),
                "--out",
                str(out),
                "--against",
                str(source),
                "--json",
            ],
        )
        assert result.exit_code == 6
        assert json.loads(result.stderr)["error_code"] == E_REPLAY_DIVERGENCE

    def test_replay_rejects_run_bundle_prefix_past_timeline(self, tmp_path: Path) -> None:
        run_dir = _make_wall_clock_fixture(tmp_path, applied_events=999)
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(run_dir / "replay.json"), "--out", str(out), "--json"],
        )
        assert result.exit_code == 6
        payload = json.loads(result.stderr)
        assert payload["error_code"] == E_REPLAY_DIVERGENCE

    def test_replay_rejects_run_bundle_mid_slow_copy_prefix(self, tmp_path: Path) -> None:
        run_dir = _make_wall_clock_fixture(
            tmp_path,
            scenario_name="slow-copy.yaml",
            applied_events=1,
        )
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(run_dir / "replay.json"), "--out", str(out), "--json"],
        )
        assert result.exit_code == 6
        payload = json.loads(result.stderr)
        assert payload["error_code"] == E_REPLAY_DIVERGENCE

    def test_replay_rejects_run_bundle_tampered_digest(self, tmp_path: Path) -> None:
        run_dir = _make_wall_clock_fixture(tmp_path, applied_events=1)
        bundle_path = run_dir / "replay.json"
        payload = json.loads(bundle_path.read_text())
        payload["journal_digest"] = "0" * 64
        bundle_path.write_text(json.dumps(payload))
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(bundle_path), "--out", str(out), "--json"],
        )
        assert result.exit_code == 6
        error = json.loads(result.stderr)
        assert error["error_code"] == E_REPLAY_DIVERGENCE

    def test_replay_run_bundle_materializer_failure_uses_error_envelope(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        run_dir = _make_wall_clock_fixture(tmp_path, applied_events=1)

        def fail_replay(_bundle, _out):
            raise FilesystemActionError(
                "phase-B replay failed",
                event_id="move_001",
                action=TimelineActionName.MOVE_ASSET,
                asset_id="asset_hd_main",
                cause=OSError("disk full"),
            )

        monkeypatch.setattr(replay_cmd, "replay_run_bundle", fail_replay)
        out = tmp_path / "replay"

        result = runner.invoke(
            app,
            ["replay", str(run_dir / "replay.json"), "--out", str(out), "--json"],
        )

        assert result.exit_code == 5
        payload = json.loads(result.stderr)
        assert payload["error_code"] == "E_MATERIALIZE_FS_FAILED"
        assert payload["asset_id"] == "asset_hd_main"
        assert payload["materialization_report_path"] == str(out / "materialization.json")


def test_compare_run_replay_compares_materialization_corruption_fields(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(
        tmp_path / "right",
        probe_outcome="failed_expected",
    )

    diff = compare_run_replay(left, right)

    assert not diff.is_clean()
    assert [item.path for item in diff.files] == ["materialization.json"]


def test_compare_run_replay_ignores_corruption_duration_ns(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left", duration_ns=1)
    right = _write_run_compare_fixture(tmp_path / "right", duration_ns=99)

    diff = compare_run_replay(left, right)

    assert diff.is_clean()


def test_compare_run_replay_ignores_toolchain_and_invocation_volatility(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(
        tmp_path / "left",
        platform="darwin",
        toolchain={"ffmpeg": "7.1.1", "ffprobe": "7.1.1"},
        invocations=[{"tool": "ffmpeg", "version": "7.1.1", "command": ["a"], "exit_code": 0}],
    )
    right = _write_run_compare_fixture(
        tmp_path / "right",
        platform="linux",
        toolchain={"ffmpeg": "8.0.0", "ffprobe": "8.0.0"},
        invocations=[{"tool": "ffmpeg", "version": "8.0.0", "command": ["b"], "exit_code": 0}],
    )

    diff = compare_run_replay(left, right)

    assert diff.is_clean()


def test_compare_run_replay_compares_report_tree(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _write_asset_report(left, content_hash="sha256:" + "1" * 64)
    _write_asset_report(right, content_hash="sha256:" + "2" * 64)

    diff = compare_run_replay(left, right)

    assert [item.path for item in diff.files] == ["reports/assets/asset_main.json"]


def test_compare_run_replay_catches_missing_report_file(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _write_asset_report(left, content_hash="sha256:" + "1" * 64)

    diff = compare_run_replay(left, right)

    assert [(item.path, item.kind) for item in diff.files] == [
        ("reports/assets/asset_main.json", "missing_in_right")
    ]


def test_compare_run_replay_compares_materialization_filesystem_actions(
    tmp_path: Path,
) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _update_materialization(
        right,
        "filesystem_actions",
        [
            {
                "event_id": "move_001",
                "action": "move_asset",
                "target_asset_id": "asset_main",
                "from_path": "movies-hd/asset_main.mkv",
                "to_path": "movies-hd/moved.mkv",
                "temp_path": None,
                "duration_ns": 1,
            }
        ],
    )

    diff = compare_run_replay(left, right)

    assert [item.path for item in diff.files] == ["materialization.json"]


def test_compare_run_replay_compares_materialization_media_actions(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _update_materialization(
        right,
        "media_actions",
        [
            {
                "event_id": "reencode_video_001",
                "action": "reencode_video",
                "target_asset_id": "asset_main",
                "input_path": "movies-hd/asset_main.mkv",
                "output_path": "movies-hd/asset_main.mkv",
                "input_version_id": "version_0001",
                "output_version_id": "version_0002",
                "output_sidecar_id": None,
                "input_content_hash": "sha256:" + "1" * 64,
                "output_content_hash": "sha256:" + "2" * 64,
                "tool_invocation_index": 0,
                "duration_ns": 1,
            }
        ],
    )

    diff = compare_run_replay(left, right)

    assert [item.path for item in diff.files] == ["materialization.json"]


def test_compare_run_replay_ignores_materialization_action_duration_ns(
    tmp_path: Path,
) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    action = {
        "event_id": "move_001",
        "action": "move_asset",
        "target_asset_id": "asset_main",
        "from_path": "movies-hd/asset_main.mkv",
        "to_path": "movies-hd/moved.mkv",
        "temp_path": None,
        "duration_ns": 1,
    }
    _update_materialization(left, "filesystem_actions", [action])
    _update_materialization(right, "filesystem_actions", [dict(action, duration_ns=99)])

    diff = compare_run_replay(left, right)

    assert diff.is_clean()


def test_replay_refuses_materialize_bundle(tmp_path: Path) -> None:
    """WHY: Sprint 5 ships the MaterializeReplayBundle variant for schema
    stability but does NOT implement materialize replay. The CLI must
    refuse with exit 1 and a structured payload so agents know to expect
    this in Sprint 9, not silently parse it as plan-only."""
    bundle_path = tmp_path / "replay.json"
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": 5,
                "chaos_librarian_version": "0.1.0",
                "scenario": "schema_version: 7\nscenario_id: x\n",
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
    assert payload["error_code"] == "E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED"
    assert payload["details"]["execution_mode"] == "materialize"


def _write_run_compare_fixture(
    root: Path,
    *,
    probe_outcome: str = "still_probeable",
    duration_ns: int = 1,
    platform: str = "test",
    toolchain: dict[str, str] | None = None,
    invocations: list[dict[str, object]] | None = None,
) -> Path:
    root.mkdir()
    (root / "library").mkdir()
    (root / "library" / "asset.mkv").write_bytes(b"same")
    (root / "manifest.current.json").write_text(json.dumps({"versions": []}), encoding="utf-8")
    (root / "replay.json").write_text(
        json.dumps(
            {
                "scenario": "schema_version: 7\n",
                "run_id": str(RUN_ID),
                "resolved_seed": 7,
                "applied_events": 1,
                "journal_digest": "0" * 64,
                "execution_mode": "run",
            }
        ),
        encoding="utf-8",
    )
    (root / "journal.jsonl").write_text("", encoding="utf-8")
    (root / "materialization.json").write_text(
        json.dumps(
            {
                "outcome": "success",
                "execution_mode": "run",
                "platform": platform,
                "toolchain": toolchain or {"ffmpeg": "7.1.1", "ffprobe": "7.1.1"},
                "invocations": invocations or [],
                "started_at": "2026-05-21T00:00:00Z",
                "finished_at": "2026-05-21T00:00:01Z",
                "corruption_actions": [
                    {
                        "event_id": "corrupt_header_001",
                        "action": "corrupt_container_header",
                        "target_asset_id": "asset_main",
                        "input_path": "movies-hd/asset_main.mkv",
                        "output_path": "movies-hd/asset_main.mkv",
                        "input_version_id": "version_0001",
                        "output_version_id": "version_0002",
                        "input_content_hash": "sha256:" + "1" * 64,
                        "output_content_hash": "sha256:" + "2" * 64,
                        "corruptor": "container_header_v1",
                        "byte_start": 0,
                        "byte_count": 64,
                        "seed_material": "container_header_v1:7:corrupt_header_001:asset_main",
                        "probe_outcome": probe_outcome,
                        "probe_error_tail": None,
                        "duration_ns": duration_ns,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def _write_asset_report(root: Path, *, content_hash: str) -> None:
    reports_dir = root / "reports" / "assets"
    reports_dir.mkdir(parents=True)
    (reports_dir / "asset_main.json").write_text(
        json.dumps({"asset_id": "asset_main", "current": {"content_hash": content_hash}}),
        encoding="utf-8",
    )


def _update_materialization(root: Path, field: str, value: object) -> None:
    path = root / "materialization.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
