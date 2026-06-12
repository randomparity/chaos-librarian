"""Per-step entity-diff tests."""

from __future__ import annotations

from typing import cast

from chaos_librarian.visualize.diff import build_diffs, diff_snapshots

CollDiff = dict[str, object]


def _snap(locations: list[dict], versions: list[dict] | None = None) -> dict:
    return {"locations": locations, "versions": versions or [], "sidecars": []}


def _locs(d: dict[str, object]) -> CollDiff:
    return cast(CollDiff, d["locations"])


def test_added_and_removed_location_ids() -> None:
    prev = _snap([{"id": "loc1", "asset_id": "a1", "path": "x.mkv"}])
    curr = _snap([{"id": "loc2", "asset_id": "a2", "path": "y.mkv"}])
    d = diff_snapshots(prev, curr)
    locs = _locs(d)
    assert locs["added"] == ["loc2"]
    assert locs["removed"] == ["loc1"]


def test_changed_location_reports_path_field() -> None:
    prev = _snap([{"id": "loc1", "asset_id": "a1", "path": "old.mkv"}])
    curr = _snap([{"id": "loc1", "asset_id": "a1", "path": "new.mkv"}])
    d = diff_snapshots(prev, curr)
    changed = cast(list[dict[str, object]], _locs(d)["changed"])
    assert len(changed) == 1
    assert changed[0]["id"] == "loc1"
    assert "path" in cast(list[str], changed[0]["fields"])
    assert cast(dict[str, object], changed[0]["from"])["path"] == "old.mkv"
    assert cast(dict[str, object], changed[0]["to"])["path"] == "new.mkv"


def test_identical_snapshots_have_no_changes() -> None:
    snap = _snap([{"id": "loc1", "asset_id": "a1", "path": "x.mkv"}])
    d = diff_snapshots(snap, snap)
    assert _locs(d) == {"added": [], "removed": [], "changed": []}


def test_build_diffs_has_one_entry_per_transition() -> None:
    snaps = [_snap([]), _snap([{"id": "l", "asset_id": "a", "path": "p"}]), _snap([])]
    diffs = build_diffs(snaps)
    assert len(diffs) == len(snaps) - 1
    assert _locs(diffs[0])["added"] == ["l"]
    assert _locs(diffs[1])["removed"] == ["l"]
