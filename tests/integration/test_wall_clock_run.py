"""Integration coverage for wall-clock run mode."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from chaos_librarian.contract.materialization import MaterializedAsset, MediaAction
from chaos_librarian.contract.run_sentinel import SENTINEL_FILENAME
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine import run_materializer_plan
from chaos_librarian.materializer import phase_b, wall_clock
from chaos_librarian.materializer.synthesis import MaterializeAssetResult
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "scenarios" / ("active-library-churn.yaml")
)
_JOURNAL_ADAPTER = TypeAdapter(JournalEntry)
_FAKE_PROVIDER = "fake-content-source"
_FAKE_RECIPE_DIGEST = "sha256:" + "f" * 64


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


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    clock = FakeClock()
    monkeypatch.setattr(wall_clock, "_monotonic_ns", clock.monotonic_ns)
    monkeypatch.setattr(wall_clock, "_sleep_until", clock.sleep_until)
    monkeypatch.setattr(wall_clock, "_utc_now", clock.utc_now)
    return clock


@pytest.fixture(autouse=True)
def fake_tool_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(phase_b, "apply_media_action", _fake_apply_media_action)


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
    data = b"wall-clock-active-library"
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


def _fake_apply_media_action(ctx, entry: JournalEntry) -> MediaAction:
    action = TimelineActionName(entry.action)
    if action is TimelineActionName.UPDATE_SIDECAR:
        sidecar_id = entry.output_version_ids[0] if entry.output_version_ids else None
        if sidecar_id is not None:
            ctx.post_phase_b_sidecars[sidecar_id] = (
                "sha256:" + hashlib.sha256(b"sidecar").hexdigest(),
                str(entry.state_delta["sidecar_path"]),
            )
    if entry.output_version_ids:
        ctx.post_phase_b_versions[entry.output_version_ids[0]] = (
            "sha256:" + hashlib.sha256(entry.event_id.encode()).hexdigest(),
            None,
        )
    return MediaAction(
        event_id=entry.event_id,
        action=action,
        target_asset_id=entry.target_ids[0],
        input_path=str(entry.state_delta.get("input_path", "")),
        output_path=str(entry.state_delta.get("output_path", "")),
        duration_ns=1,
    )


def _logical_journal(run_id, applied_events: int):
    run_input = prepare_run_input(FIXTURE)
    report = run_validation(run_input)
    return run_materializer_plan(
        run_input=run_input,
        validation_report=report,
        run_id_override=run_id,
        applied_events_override=applied_events,
    ).journal


def _strip_wall_clock(entries: tuple[JournalEntry, ...]) -> tuple[JournalEntry, ...]:
    return tuple(entry.model_copy(update={"wall_clock_time": None}) for entry in entries)


def test_active_library_churn_completes_with_run_mode(
    fake_clock: FakeClock, tmp_path: Path
) -> None:
    artifacts = wall_clock.run_wall_clock_scenario(
        FIXTURE,
        tmp_path / "run",
        duration="20ns",
        speed="1x",
    )
    assert artifacts.materialization_report.execution_mode.value == "run"
    assert artifacts.replay_bundle.execution_mode.value == "run"
    assert artifacts.replay_bundle.applied_events == 8
    report_payload = json.loads((tmp_path / "run" / "materialization.json").read_text())
    replay_payload = json.loads((tmp_path / "run" / "replay.json").read_text())
    assert report_payload["content_sources"] == replay_payload["content_sources"]
    assert report_payload["content_sources"][0]["asset_id"] == "asset_main"
    assert report_payload["content_sources"][0]["provider"] == _FAKE_PROVIDER


def test_partial_duration_journal_matches_planned_prefix(
    fake_clock: FakeClock, tmp_path: Path
) -> None:
    artifacts = wall_clock.run_wall_clock_scenario(
        FIXTURE,
        tmp_path / "run",
        duration="4ns",
        speed="1x",
    )
    actual = _strip_wall_clock(_read_journal(tmp_path / "run"))
    expected = _logical_journal(
        artifacts.replay_bundle.run_id,
        artifacts.replay_bundle.applied_events,
    )
    assert actual == expected


def test_full_duration_journal_matches_full_plan(fake_clock: FakeClock, tmp_path: Path) -> None:
    artifacts = wall_clock.run_wall_clock_scenario(
        FIXTURE,
        tmp_path / "run",
        duration="20ns",
        speed="1x",
    )
    actual = _strip_wall_clock(_read_journal(tmp_path / "run"))
    expected = _logical_journal(artifacts.replay_bundle.run_id, 8)
    assert actual == expected


def test_watcher_polling_observes_partial_slow_copy(
    fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[bytes] = []
    original = wall_clock._grow_active_slow_copies

    def spy(library_root, sessions, *, logical_ns: int) -> None:
        original(library_root, sessions, logical_ns=logical_ns)
        temp = library_root / "movies-hd" / "Pulsar Copy.mkv.part"
        if temp.exists():
            observed.append(temp.read_bytes())

    monkeypatch.setattr(wall_clock, "_grow_active_slow_copies", spy)
    wall_clock.run_wall_clock_scenario(
        FIXTURE,
        tmp_path / "run",
        duration="4ns",
        speed="1x",
    )
    assert any(0 < len(sample) < len(b"wall-clock-active-library") for sample in observed)


def test_interrupted_run_leaves_in_progress_sentinel_and_live_journal(
    fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_finalize(*_args, **_kwargs):
        raise RuntimeError("simulated interruption")

    out_dir = tmp_path / "run"
    monkeypatch.setattr(wall_clock, "_finalize_wall_clock_run", fail_finalize)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        wall_clock.run_wall_clock_scenario(FIXTURE, out_dir, duration="4ns", speed="1x")
    sentinel = json.loads((out_dir / SENTINEL_FILENAME).read_text(encoding="utf-8"))
    assert sentinel["state"] == "in_progress"
    assert (out_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()


def _read_journal(out_dir: Path) -> tuple[JournalEntry, ...]:
    return tuple(
        _JOURNAL_ADAPTER.validate_json(line)
        for line in (out_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    )
