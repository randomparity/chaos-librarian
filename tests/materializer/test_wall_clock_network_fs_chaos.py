"""Wall-clock realization tests for the network-fs-chaos actions."""

from __future__ import annotations

import hashlib
import shutil
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import (
    MaterializedAsset,
    NetworkFsChaosCondition,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer import replay as replay_mod
from chaos_librarian.materializer import wall_clock
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.replay import replay_run_bundle
from chaos_librarian.materializer.synthesis import MaterializeAssetResult

_ASSET_REL_PATH = "movies-hd/Clip/Clip - hd.mkv"


class _FakeClock:
    def __init__(self) -> None:
        self.now_ns = 0
        self.base = datetime(2026, 5, 30, tzinfo=UTC)

    def monotonic_ns(self) -> int:
        return self.now_ns

    def sleep_until(self, deadline_ns: int) -> None:
        self.now_ns = max(self.now_ns, deadline_ns)

    def utc_now(self) -> datetime:
        return self.base + timedelta(microseconds=self.now_ns // 1_000)


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
        invocation=ToolInvocation(
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
        content_sources=(
            ContentSourceEvidence(
                asset_id=asset.id,
                track_kind=ContentTrackKind.VIDEO,
                track_index=None,
                source="fake-video",
                provider="fake",
                recipe_digest="sha256:" + "f" * 64,
                cache_disposition=CacheDisposition.NOT_CACHEABLE,
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _fake_runtime(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(wall_clock, "_monotonic_ns", clock.monotonic_ns)
    monkeypatch.setattr(wall_clock, "_sleep_until", clock.sleep_until)
    monkeypatch.setattr(wall_clock, "_utc_now", clock.utc_now)
    monkeypatch.setattr(wall_clock, "detect_capabilities", _capabilities)
    monkeypatch.setattr(wall_clock, "assert_capable_for_static_materialize", lambda _caps: None)
    monkeypatch.setattr(wall_clock, "materialize_one_asset", _fake_materialize_one_asset)
    return clock


def _scenario_yaml(timeline: str) -> str:
    return (
        dedent(
            """\
        schema_version: 32
        scenario_id: network-fs-chaos-wall-clock
        seed: 7
        duration_scale: short
        profiles:
          - network-fs-chaos
        library:
          roots:
            - id: movies_hd
              path: movies-hd
        movies:
          - id: movie_001
            title: Clip
            layout: movie_folder
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
                        resolution: sd
                      audio:
                        - source: sine
                          codec: aac
                          channels: stereo
                          language: eng
        series: []
        artists: []
        """
        )
        + timeline
    )


def _run(tmp_path: Path, timeline: str, *, duration: str = "10s"):
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(_scenario_yaml(timeline))
    out_dir = tmp_path / "run"
    return wall_clock.run_wall_clock_scenario(
        scenario, out_dir, duration=duration, speed="1x"
    ), out_dir


def _library_file(out_dir: Path) -> Path:
    return out_dir / "library" / _ASSET_REL_PATH


def test_change_permissions_applies_and_restores_mode(tmp_path: Path) -> None:
    timeline = dedent(
        """\
        timeline:
          - id: chmod_001
            at: 1s
            action: change_permissions
            target: asset_main
            mode: "000"
        """
    )
    artifacts, out_dir = _run(tmp_path, timeline)

    records = artifacts.materialization_report.network_fs_chaos_actions
    assert len(records) == 1
    record = records[0]
    assert record.condition is NetworkFsChaosCondition.EACCES
    assert record.enforced is True
    assert record.mode == "000"
    # Mode restored at finalize so the tree is readable/cleanable.
    final_mode = stat.S_IMODE(_library_file(out_dir).stat().st_mode)
    assert final_mode != 0
    shutil.rmtree(out_dir)


def test_stacked_chmods_restore_to_original_mode(tmp_path: Path) -> None:
    # Two change_permissions on the same asset: restore must return the file to
    # its true pre-chaos mode, not the intermediate 000.
    timeline = dedent(
        """\
        timeline:
          - id: chmod_001
            at: 1s
            action: change_permissions
            target: asset_main
            mode: "000"
          - id: chmod_002
            at: 2s
            action: change_permissions
            target: asset_main
            mode: "444"
        """
    )
    artifacts, out_dir = _run(tmp_path, timeline)

    assert len(artifacts.materialization_report.network_fs_chaos_actions) == 2
    library_file = _library_file(out_dir)
    final_mode = stat.S_IMODE(library_file.stat().st_mode)
    # The fake synthesizer writes the file with the process default (not 000/444),
    # so a correct restore leaves a writable, non-444 mode.
    assert final_mode & stat.S_IWUSR
    assert final_mode != 0o444
    shutil.rmtree(out_dir)


def test_toggle_readonly_clears_write_bits_then_restores(tmp_path: Path) -> None:
    timeline = dedent(
        """\
        timeline:
          - id: ro_001
            at: 1s
            action: toggle_readonly
            target: asset_main
            mode: readonly
        """
    )
    artifacts, out_dir = _run(tmp_path, timeline)

    record = artifacts.materialization_report.network_fs_chaos_actions[0]
    assert record.condition is NetworkFsChaosCondition.EACCES
    assert record.enforced is True
    assert record.readonly_state is not None
    assert record.readonly_state.value == "readonly"
    final_mode = stat.S_IMODE(_library_file(out_dir).stat().st_mode)
    assert final_mode & stat.S_IWUSR
    shutil.rmtree(out_dir)


@pytest.mark.parametrize(
    ("action", "extra", "condition"),
    [
        ("simulate_quota_exceeded", "", NetworkFsChaosCondition.ENOSPC),
        ("simulate_stale_handle", "", NetworkFsChaosCondition.ESTALE),
    ],
)
def test_simulated_conditions_record_enforced_false(
    tmp_path: Path, action: str, extra: str, condition: NetworkFsChaosCondition
) -> None:
    timeline = dedent(
        f"""\
        timeline:
          - id: sim_001
            at: 1s
            action: {action}
            target: asset_main{extra}
        """
    )
    artifacts, out_dir = _run(tmp_path, timeline)

    record = artifacts.materialization_report.network_fs_chaos_actions[0]
    assert record.condition is condition
    assert record.enforced is False
    shutil.rmtree(out_dir)


def test_acquire_release_lock_records_paired_close(tmp_path: Path) -> None:
    timeline = dedent(
        """\
        timeline:
          - id: acq_001
            at: 1s
            action: acquire_lock
            target: asset_main
            lock_type: exclusive
          - id: rel_001
            at: 2s
            action: release_lock
            for: acq_001
        """
    )
    artifacts, out_dir = _run(tmp_path, timeline)

    record = artifacts.materialization_report.network_fs_chaos_actions[0]
    assert record.condition is NetworkFsChaosCondition.EAGAIN
    assert record.enforced is False
    assert record.event_id == "acq_001"
    assert record.related_event_id == "rel_001"
    assert record.related_target_ref == "asset_main"
    assert record.lock_type is not None
    assert record.lock_type.value == "exclusive"
    shutil.rmtree(out_dir)


def test_unmount_remount_records_paired_close(tmp_path: Path) -> None:
    timeline = dedent(
        """\
        timeline:
          - id: um_001
            at: 1s
            action: unmount_path
            target: asset_main
          - id: rm_001
            at: 2s
            action: remount_path
            for: um_001
        """
    )
    artifacts, out_dir = _run(tmp_path, timeline)

    record = artifacts.materialization_report.network_fs_chaos_actions[0]
    assert record.condition is NetworkFsChaosCondition.UNAVAILABLE
    assert record.event_id == "um_001"
    assert record.related_event_id == "rm_001"
    shutil.rmtree(out_dir)


def test_no_chaos_actions_leaves_empty_record_list(tmp_path: Path) -> None:
    artifacts, out_dir = _run(tmp_path, "timeline: []\n")
    assert artifacts.materialization_report.network_fs_chaos_actions == []
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    shutil.rmtree(out_dir)


def test_replay_reproduces_chaos_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(replay_mod, "materialize_one_asset", _fake_materialize_one_asset)
    monkeypatch.setattr(replay_mod, "detect_capabilities", _capabilities)
    monkeypatch.setattr(replay_mod, "assert_capable_for_static_materialize", lambda _caps: None)

    timeline = dedent(
        """\
        timeline:
          - id: chmod_001
            at: 1s
            action: change_permissions
            target: asset_main
            mode: "000"
          - id: acq_001
            at: 2s
            action: acquire_lock
            target: asset_main
            lock_type: shared
          - id: rel_001
            at: 3s
            action: release_lock
            for: acq_001
        """
    )
    artifacts, run_dir = _run(tmp_path, timeline)
    original = artifacts.materialization_report.network_fs_chaos_actions

    replay_dir = tmp_path / "replay"
    replayed = replay_run_bundle(artifacts.replay_bundle, replay_dir)
    reproduced = replayed.materialization_report.network_fs_chaos_actions

    assert [r.model_dump() for r in reproduced] == [r.model_dump() for r in original]
    shutil.rmtree(run_dir)
    shutil.rmtree(replay_dir)


def _capabilities() -> Capabilities:
    return Capabilities(
        schema_version=7,
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
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )


def test_failure_path_restores_chmod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # change_permissions to 000, then a touch_mtime that we force to raise so the
    # Phase-B failure path runs; the captured mode must still be restored.
    timeline = dedent(
        """\
        timeline:
          - id: chmod_001
            at: 1s
            action: change_permissions
            target: asset_main
            mode: "000"
          - id: touch_001
            at: 2s
            action: touch_mtime
            target: asset_main
            offset: 5s
        """
    )
    scenario_text = _scenario_yaml(timeline).replace(
        "profiles:\n  - network-fs-chaos",
        "profiles:\n  - network-fs-chaos\n  - filesystem-artifacts",
    )

    def _boom(_state, entry):
        raise FilesystemActionError(
            "boom",
            event_id=entry.event_id,
            cause=OSError("boom"),
            action=TimelineActionName(entry.action),
            asset_id="asset_main",
        )

    monkeypatch.setattr(wall_clock, "dispatch_phase_b_entry", _boom)

    scenario = tmp_path / "scenario.yaml"
    scenario.write_text(scenario_text)
    out_dir = tmp_path / "run"
    with pytest.raises(FilesystemActionError):
        wall_clock.run_wall_clock_scenario(scenario, out_dir, duration="10s", speed="1x")

    # The Phase-B failure path restores the captured mode before wiping library/,
    # so cleanup succeeds and the tree is removed rather than left at chmod 000.
    assert not (out_dir / "library").exists()
    shutil.rmtree(out_dir)
