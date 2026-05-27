"""Wall-clock materializer orchestration tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent
from typing import cast

import pytest
from pydantic import TypeAdapter

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    FilesystemAction,
    MaterializedAsset,
    OracleHashAction,
    Outcome,
)
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.materializer import phase_b, wall_clock
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
    TimelineUnsupportedError,
)
from chaos_librarian.materializer.synthesis import MaterializeAssetResult

_JOURNAL_ADAPTER = TypeAdapter(JournalEntry)
_CORRUPTED_HASH = "sha256:" + "2" * 64
_INPUT_HASH = "sha256:" + "1" * 64
_FAKE_PROVIDER = "fake-content-source"
_FAKE_RECIPE_DIGEST = "sha256:" + "f" * 64
_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 0
        self.base = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)

    def monotonic_ns(self) -> int:
        return self.now_ns

    def sleep_until(self, deadline_ns: int) -> None:
        self.now_ns = max(self.now_ns, deadline_ns)

    def utc_now(self) -> datetime:
        return self.base + timedelta(microseconds=self.now_ns // 1_000)

    def advance(self, ns: int) -> None:
        self.now_ns += ns


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr(wall_clock, "_monotonic_ns", clock.monotonic_ns)
    monkeypatch.setattr(wall_clock, "_sleep_until", clock.sleep_until)
    monkeypatch.setattr(wall_clock, "_utc_now", clock.utc_now)
    return clock


@pytest.fixture(autouse=True)
def fake_static_materializer(monkeypatch: pytest.MonkeyPatch) -> None:
    caps = Capabilities(
        schema_version=4,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
        ),
    )
    monkeypatch.setattr(wall_clock, "detect_capabilities", lambda: caps)
    monkeypatch.setattr(wall_clock, "assert_capable_for_static_materialize", lambda _caps: None)
    monkeypatch.setattr(wall_clock, "materialize_one_asset", _fake_materialize_one_asset)


def test_wall_clock_refuses_hdr_when_capability_missing(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del fake_clock
    caps = Capabilities(
        schema_version=4,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=False,
        ),
    )
    monkeypatch.setattr(wall_clock, "detect_capabilities", lambda: caps)
    scenario = tmp_path / "hdr-wall-clock.yaml"
    scenario.write_text(
        (_FIXTURE_DIR / "hevc-mkv.yaml")
        .read_text()
        .replace("resolution: sd", "resolution: sd\n                hdr_mode: hdr10")
    )
    out_dir = tmp_path / "run"

    with pytest.raises(CapabilityGateError) as exc:
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="1ns", speed="1x")

    assert exc.value.field == "ready_for.materialize_hdr_video"
    assert not out_dir.exists()


def _fake_materialize_one_asset(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    rendered_relative_path: str,
    skip_languages=frozenset(),
):
    del resolved_seed, caps, skip_languages
    data = f"{asset.id}-bytes".encode()
    path = out_dir / "library" / rendered_relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    probed = ProbedMedia(
        container=asset.container,
        duration_seconds=asset.duration_seconds,
        size_bytes=len(data),
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
    )
    return MaterializeAssetResult(
        invocation=wall_clock.ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", str(path)],
            exit_code=0,
            duration_ns=1,
        ),
        materialized_asset=MaterializedAsset(
            asset_id=asset.id,
            location_path=str(Path("library") / rendered_relative_path),
            content_hash=content_hash,
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        probed=probed,
        sidecar_hashes={},
        content_sources=(_fake_content_source(asset.id),),
    )


def _fake_content_source(asset_id: str) -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id=asset_id,
        track_kind=ContentTrackKind.VIDEO,
        track_index=None,
        source="fake-video",
        provider=_FAKE_PROVIDER,
        recipe_digest=_FAKE_RECIPE_DIGEST,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )


def _assert_fake_content_source_payload(payload: list[dict[str, object]]) -> None:
    assert payload == [
        {
            "asset_id": "asset_main",
            "track_kind": "video",
            "source": "fake-video",
            "provider": _FAKE_PROVIDER,
            "recipe_digest": _FAKE_RECIPE_DIGEST,
            "cache_disposition": "not_cacheable",
        }
    ]


def _write_scenario(
    tmp_path: Path,
    timeline: str,
    scenario_id: str = "wall-clock-test",
    profiles: str = "",
) -> Path:
    path = tmp_path / f"{scenario_id}.yaml"
    payload = dedent(
        f"""
            schema_version: 16
            scenario_id: {scenario_id}
            seed: 7
            duration_scale: short
            library:
              roots:
                - id: movies_hd
                  path: movies-hd
            movies:
              - id: movie_001
                title: Synthetic Test
                layout: movie_flat
                variants:
                  - id: variant_001
                    label: hd
                    bundle:
                      id: bundle_001
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
                            - codec: aac
                              channels: stereo
                              language: eng
            series: []
            artists: []
            timeline:
            {timeline}
            """
    )
    if profiles:
        payload = payload.replace(
            "duration_scale: short\n",
            f"duration_scale: short\nprofiles:\n{profiles}\n",
            1,
        )
    path.write_text(payload.lstrip(), encoding="utf-8")
    return path


def _write_malformed_scenario(
    tmp_path: Path,
    *,
    event_at: str,
    scenario_id: str = "wall-clock-corruption-test",
) -> Path:
    path = tmp_path / f"{scenario_id}.yaml"
    path.write_text(
        dedent(
            f"""
            schema_version: 16
            scenario_id: {scenario_id}
            seed: 7
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
                  - id: variant_001
                    label: hd
                    bundle:
                      id: bundle_001
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
                            - codec: aac
                              channels: stereo
                              language: eng
            series: []
            artists: []
            timeline:
              - id: corrupt_header_001
                at: {event_at}
                action: corrupt_container_header
                target: asset_main
                bytes: 64
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return path


def _journal_entries(out_dir: Path) -> list[JournalEntry]:
    return [
        _JOURNAL_ADAPTER.validate_json(line)
        for line in (out_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    ]


def test_non_adjacent_slow_copy_raises_before_out_dir(tmp_path: Path) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: copy_start
                at: 0ns
                action: slow_copy_start
                target: asset_main
                to: movies-hd/final.mkv
                temp_path: movies-hd/final.mkv.part
                duration: 10ns
              - id: sidecar_001
                at: 1ns
                action: create_sidecar
                target: asset_main
                to: movies-hd/asset_main.nfo
                kind: nfo
              - id: copy_commit
                at: 10ns
                action: slow_copy_commit
                for: copy_start
        """,
        scenario_id="non-adjacent-slow-copy",
    )
    out_dir = tmp_path / "run"
    with pytest.raises(TimelineUnsupportedError):
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="1ns", speed="1x")
    assert not out_dir.exists()


def test_timeline_drained_early_idles_until_duration(fake_clock: FakeClock, tmp_path: Path) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: move_001
                at: 1ns
                action: move_asset
                target: asset_main
                to: movies-hd/moved.mkv
        """,
    )
    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        tmp_path / "run",
        duration="10ns",
        speed="1x",
    )
    assert fake_clock.now_ns == 10
    assert artifacts.materialization_report.actual_duration_ns == 10
    assert artifacts.replay_bundle.applied_events == 1


def test_handler_overrun_does_not_start_second_due_event(
    fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: move_001
                at: 0ns
                action: move_asset
                target: asset_main
                to: movies-hd/moved.mkv
              - id: rename_001
                at: 1ns
                action: rename_file
                target: asset_main
                to: movies-hd/renamed.mkv
        """,
    )

    def slow_dispatch(ctx, entry):
        fake_clock.advance(10)
        return FilesystemAction(
            event_id=entry.event_id,
            action=TimelineActionName(entry.action),
            target_asset_id=entry.target_ids[0],
            from_path=None,
            to_path=None,
            temp_path=None,
            duration_ns=10,
        )

    monkeypatch.setattr(phase_b, "apply_filesystem_action", slow_dispatch)
    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        tmp_path / "run",
        duration="1ns",
        speed="1x",
    )
    assert artifacts.replay_bundle.applied_events == 1


def test_mid_slow_copy_timeout_executes_commit_and_marks_overrun(
    fake_clock: FakeClock, tmp_path: Path
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: copy_start
                at: 0ns
                action: slow_copy_start
                target: asset_main
                to: movies-hd/final.mkv
                temp_path: movies-hd/final.mkv.part
                duration: 10ns
              - id: copy_commit
                at: 10ns
                action: slow_copy_commit
                for: copy_start
        """,
    )
    out_dir = tmp_path / "run"
    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="5ns",
        speed="1x",
    )
    assert fake_clock.now_ns == 10
    assert artifacts.replay_bundle.applied_events == 2
    assert artifacts.materialization_report.overran_duration is True
    assert artifacts.materialization_report.actual_duration_ns == 10
    assert (out_dir / "library" / "movies-hd" / "final.mkv").read_bytes() == b"asset_main-bytes"
    assert not (out_dir / "library" / "movies-hd" / "final.mkv.part").exists()


def test_delayed_rename_keeps_old_path_visible_until_lag_commit(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: rename_001
                at: 0ns
                action: rename_file
                target: asset_main
                to: movies-hd/renamed.mkv
              - id: lag_start_001
                at: 0ns
                action: network_lag_start
                effect: delayed_rename
                target: asset_main
                after: rename_001
                duration: 10ns
              - id: lag_commit_001
                at: 10ns
                action: network_lag_commit
                for: lag_start_001
        """,
        scenario_id="delayed-rename",
        profiles="  - network-fs-lag",
    )
    out_dir = tmp_path / "run"
    old_path = out_dir / "library" / "movies-hd" / "Synthetic Test - hd.mkv"
    new_path = out_dir / "library" / "movies-hd" / "renamed.mkv"
    observations: list[tuple[bool, bool]] = []

    def observe_sleep(deadline_ns: int) -> None:
        if deadline_ns == 10:
            observations.append((old_path.exists(), new_path.exists()))
        fake_clock.sleep_until(deadline_ns)

    monkeypatch.setattr(wall_clock, "_sleep_until", observe_sleep)

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="20ns",
        speed="1x",
    )

    assert observations == [(True, False)]
    assert not old_path.exists()
    assert new_path.read_bytes() == b"asset_main-bytes"
    assert artifacts.materialization_report.network_lag_actions[0].effect.value == (
        "delayed_rename"
    )
    assert artifacts.materialization_report.network_lag_actions[0].enforced is True


def test_delayed_visibility_keeps_restored_path_absent_until_lag_commit(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: delete_001
                at: 0ns
                action: delete_file
                target: asset_main
              - id: add_001
                at: 1ns
                action: add_file
                target: asset_main
                to: movies-hd/restored.mkv
              - id: lag_start_001
                at: 1ns
                action: network_lag_start
                effect: delayed_visibility
                target: asset_main
                after: add_001
                duration: 10ns
              - id: lag_commit_001
                at: 11ns
                action: network_lag_commit
                for: lag_start_001
        """,
        scenario_id="delayed-visibility",
        profiles="  - network-fs-lag",
    )
    out_dir = tmp_path / "run"
    restored_path = out_dir / "library" / "movies-hd" / "restored.mkv"
    observations: list[bool] = []

    def observe_sleep(deadline_ns: int) -> None:
        if deadline_ns == 11:
            observations.append(restored_path.exists())
        fake_clock.sleep_until(deadline_ns)

    monkeypatch.setattr(wall_clock, "_sleep_until", observe_sleep)

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="20ns",
        speed="1x",
    )

    assert observations == [False]
    assert restored_path.read_bytes() == b"asset_main-bytes"
    action = artifacts.materialization_report.network_lag_actions[0]
    assert action.effect.value == "delayed_visibility"
    assert action.from_path is None
    assert action.to_path == "movies-hd/restored.mkv"
    assert action.enforced is True


def test_mid_network_lag_timeout_executes_commit_and_marks_overrun(
    fake_clock: FakeClock, tmp_path: Path
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: rename_001
                at: 0ns
                action: rename_file
                target: asset_main
                to: movies-hd/renamed.mkv
              - id: lag_start_001
                at: 0ns
                action: network_lag_start
                effect: delayed_rename
                target: asset_main
                after: rename_001
                duration: 10ns
              - id: lag_commit_001
                at: 10ns
                action: network_lag_commit
                for: lag_start_001
        """,
        scenario_id="delayed-rename-timeout",
        profiles="  - network-fs-lag",
    )
    out_dir = tmp_path / "run"

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="5ns",
        speed="1x",
    )

    assert fake_clock.now_ns == 10
    assert artifacts.replay_bundle.applied_events == 3
    assert artifacts.materialization_report.overran_duration is True
    assert (out_dir / "library" / "movies-hd" / "renamed.mkv").read_bytes() == (b"asset_main-bytes")


def test_held_handle_records_unenforced_local_audit(fake_clock: FakeClock, tmp_path: Path) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: rename_001
                at: 0ns
                action: rename_file
                target: asset_main
                to: movies-hd/renamed.mkv
              - id: lag_start_001
                at: 0ns
                action: network_lag_start
                effect: held_handle
                target: asset_main
                after: rename_001
                duration: 1ns
              - id: lag_commit_001
                at: 1ns
                action: network_lag_commit
                for: lag_start_001
        """,
        scenario_id="held-handle",
        profiles="  - network-fs-lag",
    )

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        tmp_path / "run",
        duration="2ns",
        speed="1x",
    )

    assert fake_clock.now_ns == 2
    assert len(artifacts.materialization_report.network_lag_actions) == 1
    action = artifacts.materialization_report.network_lag_actions[0]
    assert action.effect.value == "held_handle"
    assert action.provider == "stdlib-local"
    assert action.enforced is False


def test_interceptor_catalog_run_records_network_lag_evidence(
    fake_clock: FakeClock, tmp_path: Path
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: rename_001
                at: 1s
                action: rename_file
                target: asset_main
                to: movies-hd/catalog-renamed.mkv
              - id: delayed_rename_start
                at: 1s
                action: network_lag_start
                effect: delayed_rename
                target: asset_main
                after: rename_001
                duration: 1s
              - id: delayed_rename_commit
                at: 2s
                action: network_lag_commit
                for: delayed_rename_start
              - id: rename_for_held
                at: 3s
                action: rename_file
                target: asset_main
                to: movies-hd/catalog-held.mkv
              - id: held_handle_start
                at: 3s
                action: network_lag_start
                effect: held_handle
                target: asset_main
                after: rename_for_held
                duration: 1s
              - id: held_handle_commit
                at: 4s
                action: network_lag_commit
                for: held_handle_start
              - id: delete_for_visibility
                at: 5s
                action: delete_file
                target: asset_main
              - id: restore_for_visibility
                at: 6s
                action: add_file
                target: asset_main
                to: movies-hd/catalog-restored.mkv
              - id: delayed_visibility_start
                at: 6s
                action: network_lag_start
                effect: delayed_visibility
                target: asset_main
                after: restore_for_visibility
                duration: 1s
              - id: delayed_visibility_commit
                at: 7s
                action: network_lag_commit
                for: delayed_visibility_start
        """,
        scenario_id="interceptor-catalog-run",
        profiles="  - network-fs-lag",
    )

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        tmp_path / "run",
        duration="8s",
        speed="1x",
    )

    actions_by_effect = {
        action.effect.value: action
        for action in artifacts.materialization_report.network_lag_actions
    }
    assert fake_clock.now_ns == 8_000_000_000
    assert {"delayed_rename", "delayed_visibility", "held_handle"} <= actions_by_effect.keys()
    assert actions_by_effect["held_handle"].enforced is False


def test_active_slow_copy_grows_during_idle_waits(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_sizes: list[int] = []
    original = wall_clock._grow_active_slow_copies

    def spy(library_root, sessions, *, logical_ns: int) -> None:
        original(library_root, sessions, logical_ns=logical_ns)
        temp = library_root / "movies-hd" / "Nova.mkv.part"
        if temp.exists():
            observed_sizes.append(temp.stat().st_size)

    monkeypatch.setattr(wall_clock, "_grow_active_slow_copies", spy)

    scenario = _write_scenario(
        tmp_path,
        """
              - id: copy_start_001
                at: 1s
                action: slow_copy_start
                target: asset_main
                to: movies-hd/Nova.mkv
                temp_path: movies-hd/Nova.mkv.part
                duration: 3s
              - id: copy_commit_001
                at: 4s
                action: slow_copy_commit
                for: copy_start_001
        """,
        scenario_id="slow-copy-materialize",
    )
    wall_clock.run_wall_clock_scenario(scenario, tmp_path / "run", duration="5s", speed="1x")

    source_size = len(b"asset_main-bytes")
    partial_sizes = {size for size in observed_sizes if 0 < size < source_size}
    assert len(partial_sizes) >= 2


def test_filesystem_failure_writes_run_failure_metadata(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: move_001
                at: 0ns
                action: move_asset
                target: asset_main
                to: movies-hd/moved.mkv
        """,
    )
    out_dir = tmp_path / "run"

    def fail_dispatch(ctx, entry):
        del ctx
        raise FilesystemActionError(
            "move failed",
            event_id=entry.event_id,
            action=TimelineActionName(entry.action),
            asset_id=entry.target_ids[0],
            cause=OSError("disk full"),
        )

    monkeypatch.setattr(phase_b, "apply_filesystem_action", fail_dispatch)
    with pytest.raises(FilesystemActionError, match="move failed"):
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="1ns", speed="1x")

    report = json.loads((out_dir / "materialization.json").read_text(encoding="utf-8"))
    sentinel = json.loads((out_dir / ".chaos-librarian-run").read_text(encoding="utf-8"))
    assert report["outcome"] == "fs_failed"
    assert report["execution_mode"] == "run"
    assert report["requested_duration_ns"] == 1
    assert sentinel["state"] == "complete"
    assert not (out_dir / "library").exists()


def test_media_failure_writes_run_failure_metadata(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: sidecar_001
                at: 0ns
                action: create_sidecar
                target: asset_main
                to: movies-hd/asset_main.nfo
                kind: nfo
        """,
    )
    out_dir = tmp_path / "run"

    def fail_media(ctx, entry):
        del ctx
        raise MediaActionError(
            "sidecar failed",
            event_id=entry.event_id,
            action=TimelineActionName(entry.action),
            asset_id=entry.target_ids[0],
            cause=RuntimeError("generator failed"),
        )

    monkeypatch.setattr(phase_b, "apply_media_action", fail_media)
    with pytest.raises(MediaActionError, match="sidecar failed"):
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="1ns", speed="1x")

    report = json.loads((out_dir / "materialization.json").read_text(encoding="utf-8"))
    sentinel = json.loads((out_dir / ".chaos-librarian-run").read_text(encoding="utf-8"))
    assert report["outcome"] == "media_failed"
    assert report["execution_mode"] == "run"
    assert report["failures"][0]["stage"] == "media"
    assert sentinel["state"] == "complete"
    assert not (out_dir / "library").exists()


def test_run_applies_corruption_only_when_due(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_successful_corruption(monkeypatch)
    scenario = _write_malformed_scenario(tmp_path, event_at="0ns")
    out_dir = tmp_path / "run"

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="1ns",
        speed="1x",
    )

    assert fake_clock.now_ns == 1
    assert artifacts.replay_bundle.applied_events == 1
    assert artifacts.materialization_report.corruption_actions == [
        _corruption_action(
            output_version_id=artifacts.materialization_report.corruption_actions[
                0
            ].output_version_id
        )
    ]
    corrupted = _corrupted_version_payload(out_dir)
    assert corrupted["content_hash"] == _CORRUPTED_HASH
    corruption = cast("dict[str, object]", corrupted["corruption"])
    assert corruption["event_id"] == "corrupt_header_001"


def test_run_omits_future_corruption_actions(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_successful_corruption(monkeypatch)
    scenario = _write_malformed_scenario(tmp_path, event_at="10ns")
    out_dir = tmp_path / "run"

    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="1ns",
        speed="1x",
    )

    assert fake_clock.now_ns == 1
    assert artifacts.replay_bundle.applied_events == 0
    assert artifacts.materialization_report.corruption_actions == []
    manifest = json.loads((out_dir / "manifest.current.json").read_text(encoding="utf-8"))
    assert all("corruption" not in version for version in manifest["versions"])


def test_run_corruption_failure_maps_to_corruption_failed(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_failing_corruption(monkeypatch)
    scenario = _write_malformed_scenario(tmp_path, event_at="0ns")
    out_dir = tmp_path / "run"

    with pytest.raises(CorruptionActionError, match="short file"):
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="1ns", speed="1x")

    report = json.loads((out_dir / "materialization.json").read_text(encoding="utf-8"))
    assert report["outcome"] == Outcome.CORRUPTION_FAILED.value
    assert report["execution_mode"] == "run"
    assert report["failures"][0]["stage"] == FailureStage.CORRUPTION.value
    assert report["failures"][0]["stderr_tail"] == "short file"
    assert not (out_dir / "library").exists()
    assert fake_clock.now_ns == 0


def test_run_oracle_hash_failure_preserves_partial_actions(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_second_oracle_hash_failure(monkeypatch)
    scenario = _write_scenario(
        tmp_path,
        """
              - id: wrong_hash_001
                at: 0ns
                action: wrong_oracle_hash
                target: asset_main
              - id: wrong_hash_002
                at: 1ns
                action: wrong_oracle_hash
                target: asset_main
        """,
        scenario_id="wall-clock-oracle-failure-test",
        profiles="  - negative-oracle",
    )
    out_dir = tmp_path / "run"

    with pytest.raises(CorruptionActionError, match="hash failed"):
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="2ns", speed="1x")

    report = json.loads((out_dir / "materialization.json").read_text(encoding="utf-8"))
    assert report["outcome"] == Outcome.CORRUPTION_FAILED.value
    assert report["oracle_hash_actions"][0]["event_id"] == "wrong_hash_001"
    assert report["oracle_hash_actions"][0]["reported_content_hash"] == "sha256:" + "9" * 64
    assert not (out_dir / "library").exists()
    assert fake_clock.now_ns == 1


def test_slow_copy_partial_growth_writes_exact_prefix(tmp_path: Path) -> None:
    library = tmp_path / "library"
    session = wall_clock.WallClockSlowCopySession(
        start_event_id="copy_start",
        asset_id="asset_main",
        source_bytes=b"0123456789",
        temp_path="movies-hd/file.part",
        final_path="movies-hd/file.mkv",
        start_logical_ns=0,
        commit_logical_ns=10,
        total_bytes=10,
    )
    wall_clock._grow_active_slow_copies(library, {"copy_start": session}, logical_ns=5)
    assert (library / "movies-hd" / "file.part").read_bytes() == b"01234"


def test_final_journal_keeps_timestamps_and_digest_normalizes(
    fake_clock: FakeClock,
    tmp_path: Path,
) -> None:
    scenario = _write_scenario(
        tmp_path,
        """
              - id: move_001
                at: 0ns
                action: move_asset
                target: asset_main
                to: movies-hd/moved.mkv
              - id: rename_001
                at: 1ns
                action: rename_file
                target: asset_main
                to: movies-hd/renamed.mkv
        """,
    )
    out_dir = tmp_path / "run"
    artifacts = wall_clock.run_wall_clock_scenario(
        scenario,
        out_dir,
        duration="10ns",
        speed="1x",
    )
    entries = _journal_entries(out_dir)
    assert entries
    assert all(entry.wall_clock_time is not None for entry in entries)
    digest_entries = [entry.model_copy(update={"wall_clock_time": None}) for entry in entries]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    assert artifacts.replay_bundle.journal_digest == digest
    replay_payload = json.loads((out_dir / "replay.json").read_text(encoding="utf-8"))
    assert replay_payload["run_id"] == str(artifacts.materialization_report.run_id)
    report_payload = json.loads((out_dir / "materialization.json").read_text(encoding="utf-8"))
    _assert_fake_content_source_payload(report_payload["content_sources"])
    _assert_fake_content_source_payload(replay_payload["content_sources"])


def _patch_successful_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx, entry: JournalEntry) -> CorruptionAction:
        output_version_id = entry.output_version_ids[0]
        ctx.post_phase_b_versions[output_version_id] = (
            _CORRUPTED_HASH,
            ProbedMedia(container="mkv", duration_seconds=1.0, size_bytes=128, streams=[]),
        )
        return _corruption_action(output_version_id=output_version_id)

    monkeypatch.setattr(phase_b, "apply_corruption_action", fake_apply)


def _patch_failing_corruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(_ctx, entry: JournalEntry) -> CorruptionAction:
        raise CorruptionActionError(
            "corrupt_container_header failed for event corrupt_header_001: short file",
            event_id=entry.event_id,
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            cause=RuntimeError("short file"),
            asset_id=entry.target_ids[0],
        )

    monkeypatch.setattr(phase_b, "apply_corruption_action", fake_apply)


def _patch_second_oracle_hash_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_apply(ctx, entry: JournalEntry) -> OracleHashAction:
        if entry.event_id == "wrong_hash_002":
            raise CorruptionActionError(
                "wrong_oracle_hash failed for event wrong_hash_002: hash failed",
                event_id=entry.event_id,
                action=TimelineActionName.WRONG_ORACLE_HASH,
                cause=RuntimeError("hash failed"),
                asset_id=entry.target_ids[0],
            )
        output_version_id = entry.output_version_ids[0]
        reported_hash = "sha256:" + "9" * 64
        ctx.post_phase_b_oracle_hashes[output_version_id] = (
            reported_hash,
            ProbedMedia(container="mkv", duration_seconds=1.0, size_bytes=16, streams=[]),
        )
        return OracleHashAction(
            event_id=entry.event_id,
            action=TimelineActionName.WRONG_ORACLE_HASH,
            target_asset_id=entry.target_ids[0],
            input_path="movies-hd/Synthetic Test - hd.mkv",
            output_path="movies-hd/Synthetic Test - hd.mkv",
            input_version_id=entry.input_version_ids[0],
            output_version_id=output_version_id,
            actual_content_hash=_INPUT_HASH,
            reported_content_hash=reported_hash,
            seed_material="wrong_oracle_hash_v1:7:wrong_hash_001:asset_main",
            duration_ns=1,
        )

    monkeypatch.setattr(phase_b, "apply_wrong_oracle_hash", fake_apply)


def _corruption_action(*, output_version_id: str) -> CorruptionAction:
    return CorruptionAction(
        event_id="corrupt_header_001",
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_asset_id="asset_main",
        input_path="movies-hd/Broken Header - hd.mkv",
        output_path="movies-hd/Broken Header - hd.mkv",
        input_version_id="version_0001",
        output_version_id=output_version_id,
        input_content_hash=_INPUT_HASH,
        output_content_hash=_CORRUPTED_HASH,
        corruptor="container_header_v1",
        input_size_bytes=128,
        output_size_bytes=128,
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:7:corrupt_header_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
        duration_ns=1,
    )


def _corrupted_version_payload(out_dir: Path) -> dict[str, object]:
    manifest = json.loads((out_dir / "manifest.current.json").read_text(encoding="utf-8"))
    for version in manifest["versions"]:
        if version.get("corruption") is not None:
            return version
    raise AssertionError("expected corrupted version in manifest.current.json")
