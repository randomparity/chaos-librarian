"""Per-step entity-diff tests."""

from __future__ import annotations

from typing import cast

from chaos_librarian.visualize.diff import build_diffs, diff_snapshots


def _changed(collection: dict[str, object]) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", collection["changed"])


def _snap(
    locations: list[dict[str, object]],
    versions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {"locations": locations, "versions": versions or [], "sidecars": []}


def test_added_and_removed_location_ids() -> None:
    prev = _snap([{"id": "loc1", "asset_id": "a1", "path": "x.mkv"}])
    curr = _snap([{"id": "loc2", "asset_id": "a2", "path": "y.mkv"}])
    d = diff_snapshots(prev, curr)
    assert d["locations"]["added"] == ["loc2"]
    assert d["locations"]["removed"] == ["loc1"]


def test_changed_location_reports_path_field() -> None:
    prev = _snap([{"id": "loc1", "asset_id": "a1", "path": "old.mkv"}])
    curr = _snap([{"id": "loc1", "asset_id": "a1", "path": "new.mkv"}])
    d = diff_snapshots(prev, curr)
    changed = _changed(d["locations"])
    assert changed == [
        {
            "id": "loc1",
            "fields": ["path"],
            "from": {"id": "loc1", "asset_id": "a1", "path": "old.mkv"},
            "to": {"id": "loc1", "asset_id": "a1", "path": "new.mkv"},
        }
    ]


def test_identical_snapshots_have_no_changes() -> None:
    snap = _snap([{"id": "loc1", "asset_id": "a1", "path": "x.mkv"}])
    d = diff_snapshots(snap, snap)
    assert d["locations"] == {"added": [], "removed": [], "changed": []}


def test_build_diffs_has_one_entry_per_transition() -> None:
    snaps = [_snap([]), _snap([{"id": "l", "asset_id": "a", "path": "p"}]), _snap([])]
    diffs = build_diffs(snaps)
    assert len(diffs) == len(snaps) - 1
    assert diffs[0]["locations"]["added"] == ["l"]
    assert diffs[1]["locations"]["removed"] == ["l"]


def test_versions_collection_diff() -> None:
    prev = _snap([], versions=[{"id": "v1", "hash": "old"}])
    curr = _snap([], versions=[{"id": "v1", "hash": "new"}, {"id": "v2", "hash": "x"}])
    d = diff_snapshots(prev, curr)
    assert d["versions"]["added"] == ["v2"]
    changed = _changed(d["versions"])
    assert changed == [
        {
            "id": "v1",
            "fields": ["hash"],
            "from": {"id": "v1", "hash": "old"},
            "to": {"id": "v1", "hash": "new"},
        }
    ]
