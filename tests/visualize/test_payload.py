"""Payload-assembly tests, including the materialize-equivalence prerequisite."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast

import pytest

from chaos_librarian.visualize import build_payload

_FIXTURE = "tests/fixtures/scenarios/active-library-churn.yaml"
_TV_FIXTURE = "tests/fixtures/scenarios/tv-season-folders.yaml"
_SUB_FIXTURE = "tests/fixtures/scenarios/embed-extract-roundtrip.yaml"
_STATIC_FIXTURE = "tests/fixtures/scenarios/static-library.yaml"  # timeline: [] (empty)


def _plan_fixture(tmp_path: Path, fixture: str) -> Path:
    out = tmp_path / "run"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "run", "chaos-librarian", "plan", fixture, "--out", str(out)],
        check=True,
        capture_output=True,
    )
    return out


def _plan(tmp_path: Path) -> Path:
    return _plan_fixture(tmp_path, _FIXTURE)


def _changed_field_appears(payload: dict[str, object], collection: str, field: str) -> bool:
    diffs = cast("list[dict[str, object]]", payload["diffs"])
    return any(
        any(
            field in cast("list[str]", c["fields"])
            for c in cast(
                "list[dict[str, object]]",
                cast("dict[str, object]", diff[collection])["changed"],
            )
        )
        for diff in diffs
    )


def test_payload_shape(tmp_path: Path) -> None:
    payload = build_payload(_plan(tmp_path))
    assert set(payload) >= {"meta", "snapshots", "events", "diffs", "probed_final"}
    snapshots = cast("list[object]", payload["snapshots"])
    events = cast("list[object]", payload["events"])
    diffs = cast("list[object]", payload["diffs"])
    assert len(snapshots) == len(events) + 1
    assert len(diffs) == len(events)
    meta = cast("dict[str, object]", payload["meta"])
    assert meta["scenario_id"]
    assert meta["live_count"] == len(events)
    assert meta["ended_mid_write"] is False


def test_planned_events_flagged_for_prefix_run(tmp_path: Path) -> None:
    out = tmp_path / "run"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "run", "chaos-librarian", "plan", _FIXTURE, "--out", str(out), "--steps", "1"],
        check=True,
        capture_output=True,
    )
    payload = build_payload(out)
    events = cast("list[dict[str, object]]", payload["events"])
    executed = [e["executed"] for e in events]
    assert executed[0] is True
    assert executed[-1] is False  # tail is planned-but-not-executed


def test_plan_only_has_no_probed_final(tmp_path: Path) -> None:
    payload = build_payload(_plan(tmp_path))
    assert payload["probed_final"] is None


def test_declared_tracks_present_in_plan_only(tmp_path: Path) -> None:
    # static-library declares video+audio+subtitle on a_sd_main; the declared
    # layout must reach the payload even though plan-only has no probed data.
    payload = build_payload(_plan_fixture(tmp_path, _STATIC_FIXTURE))
    assert payload["probed_final"] is None
    declared = cast("dict[str, list[dict[str, object]]]", payload["declared_tracks"])
    rows = declared["a_sd_main"]
    assert [r["kind"] for r in rows] == ["video", "audio", "subtitle"]
    audio = next(r for r in rows if r["kind"] == "audio")
    assert audio["codec"] == "aac"
    assert audio["language"] == "eng"
    subtitle = next(r for r in rows if r["kind"] == "subtitle")
    assert subtitle["codec"] == "srt"


def test_empty_timeline_renders_step_zero(tmp_path: Path) -> None:
    # static-library.yaml has `timeline: []` (a genuine empty timeline — 0 journal
    # lines), so resolve_timeline() is empty: events/diffs empty, only the seeded
    # initial snapshot. NOT the same as `--steps 0` on a scenario that HAS a timeline.
    payload = build_payload(_plan_fixture(tmp_path, _STATIC_FIXTURE))
    assert payload["events"] == []
    assert payload["diffs"] == []
    snapshots = cast("list[object]", payload["snapshots"])
    assert len(snapshots) == 1
    meta = cast("dict[str, object]", payload["meta"])
    assert meta["live_count"] == 0
    assert meta["total_events"] == 0


def test_probed_for_unknown_asset_is_dropped_with_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Probed entries whose asset_id is absent from the final replayed snapshot are
    # dropped with a warning. Inject a probed version for a ghost asset into
    # manifest.current.json (kept a valid Manifest) and assert it is excluded.
    run_dir = _plan(tmp_path)
    current_path = run_dir / "manifest.current.json"
    current = json.loads(current_path.read_text())
    current["versions"].append(
        {
            "id": "ghost_v",
            "asset_id": "ghost_asset_not_in_run",
            "index": 0,
            "probed": {
                "container": "mkv",
                "duration_seconds": 1.0,
                "size_bytes": 1,
                "streams": [],
            },
        }
    )
    current_path.write_text(json.dumps(current))
    with caplog.at_level("WARNING"):
        payload = build_payload(run_dir)
    assert payload["probed_final"] is None
    assert "ghost_asset_not_in_run" in caplog.text


def test_malformed_current_manifest_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run_dir = _plan(tmp_path)
    (run_dir / "manifest.current.json").write_text("{ this is not valid json")
    with caplog.at_level("WARNING"):
        payload = build_payload(run_dir)
    # Core timeline still builds; only the optional probed section is dropped.
    assert payload["probed_final"] is None
    assert "malformed manifest.current.json" in caplog.text
    assert payload["events"]  # the rest of the payload is intact


def test_hierarchy_event_surfaces_as_location_path_change(tmp_path: Path) -> None:
    # Spec finding 2: renumber_episode / move_episode_to_season re-render episode
    # file paths (verified: tv-season-folders emits path_moves). to_manifest()
    # re-renders locations[].path, so the indirect change appears as a location
    # "path" change in some diff.
    payload = build_payload(_plan_fixture(tmp_path, _TV_FIXTURE))
    events = cast("list[dict[str, object]]", payload["events"])
    actions = {e["action"] for e in events}
    # Non-vacuous witness guard: fail loudly if the fixture stops containing the
    # path-moving hierarchy events.
    assert {"renumber_episode", "move_episode_to_season"} & actions
    assert _changed_field_appears(payload, "locations", "path")


def test_embed_subtitle_surfaces_as_version_or_sidecar_change(tmp_path: Path) -> None:
    payload = build_payload(_plan_fixture(tmp_path, _SUB_FIXTURE))
    diffs = cast("list[dict[str, object]]", payload["diffs"])
    touched = any(
        cast("list[object]", cast("dict[str, object]", diff["versions"])["added"])
        or cast("list[object]", cast("dict[str, object]", diff["versions"])["changed"])
        or cast("list[object]", cast("dict[str, object]", diff["sidecars"])["added"])
        or cast("list[object]", cast("dict[str, object]", diff["sidecars"])["changed"])
        for diff in diffs
    )
    assert touched


def _media_toolchain_available() -> bool:
    # Runtime probe (NOT a module-level skipif) so the subprocess is paid only
    # when this test actually runs.
    return (
        subprocess.run(
            ["uv", "run", "chaos-librarian", "capabilities"], capture_output=True, check=False
        ).returncode
        == 0
    )


def test_materialize_run_dir_passes_cross_check(tmp_path: Path) -> None:
    # Spec prerequisite: plan-path replay must be journal-equivalent for a
    # materialize bundle. If this raises JournalDivergenceError the equivalence
    # assumption is broken (blocking design revision, not a runtime fallback).
    if not _media_toolchain_available():
        pytest.skip("media toolchain unavailable")
    out = tmp_path / "mrun"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "run", "chaos-librarian", "materialize", _FIXTURE, "--out", str(out)],
        check=True,
        capture_output=True,
    )
    payload = build_payload(out)
    assert payload["probed_final"] is not None
    snapshots = cast("list[object]", payload["snapshots"])
    events = cast("list[object]", payload["events"])
    assert len(snapshots) == len(events) + 1


def test_diff_ids_reference_adjacent_snapshots(tmp_path: Path) -> None:
    # Spec contract: every id referenced by a diff must be present in its
    # adjacent snapshots — added/changed ids in snaps[i+1], removed ids in snaps[i].
    payload = build_payload(_plan(tmp_path))
    snaps = cast("list[dict[str, object]]", payload["snapshots"])
    diffs = cast("list[dict[str, object]]", payload["diffs"])
    for i, diff in enumerate(diffs):
        for coll in ("locations", "versions", "sidecars"):
            prev_ids = {r["id"] for r in cast("list[dict[str, object]]", snaps[i][coll])}
            curr_ids = {r["id"] for r in cast("list[dict[str, object]]", snaps[i + 1][coll])}
            diff_coll = cast("dict[str, object]", diff[coll])
            for cid in cast("list[str]", diff_coll["added"]):
                assert cid in curr_ids, (
                    f"diff[{i}].{coll}.added id {cid!r} missing from snapshots[{i + 1}]"
                )
            for cid in cast("list[str]", diff_coll["removed"]):
                assert cid in prev_ids, (
                    f"diff[{i}].{coll}.removed id {cid!r} missing from snapshots[{i}]"
                )
            for ch in cast("list[dict[str, object]]", diff_coll["changed"]):
                chid = cast("str", ch["id"])
                assert chid in curr_ids, (
                    f"diff[{i}].{coll}.changed id {chid!r} missing from snapshots[{i + 1}]"
                )
                assert chid in prev_ids, (
                    f"diff[{i}].{coll}.changed id {chid!r} missing from snapshots[{i}]"
                )
