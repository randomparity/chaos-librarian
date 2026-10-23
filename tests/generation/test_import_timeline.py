"""Imported chaos stays bounded, deterministic and safe for existing media."""

from pathlib import PurePosixPath

import pytest

from chaos_librarian.generation.import_timeline import plan_import_timeline


def _plan(
    *,
    assets: list[tuple[str, str]] | None = None,
    reserved_ids: set[str] | None = None,
    reserved_paths: set[str] | None = None,
    seed: int = 42,
    event_count: int = 32,
) -> list[dict[str, object]]:
    return plan_import_timeline(
        assets=[("video", "mkv"), ("audio", "flac")] if assets is None else assets,
        root_path="library",
        reserved_ids={"main", "video", "audio", "sidecar"}
        if reserved_ids is None
        else reserved_ids,
        reserved_paths={"library/Movie/movie.mkv", "library/Movie/poster.jpg"}
        if reserved_paths is None
        else reserved_paths,
        seed=seed,
        event_count=event_count,
    )


def test_import_mutations_are_seeded_bounded_and_byte_preserving() -> None:
    events = _plan()
    assert events == _plan(assets=[("audio", "flac"), ("video", "mkv")])
    assert events != _plan(seed=43)
    assert len(events) == 32
    assert events[0]["action"] == "rename_file"
    assert {event["action"] for event in events} == {"rename_file", "move_asset", "touch_mtime"}
    assert [event["at"] for event in events] == [f"{n}ns" for n in range(1, 33)]
    assert {event["target"] for event in events} == {"video", "audio"}
    assert len({event["id"] for event in events}) == 32
    assert _plan(assets=[("only", "mkv")], event_count=1)[0]["target"] == "only"
    assert len(_plan(event_count=1000)) == 1000


def test_import_mutations_reserve_entity_ids_and_media_sidecar_paths() -> None:
    events = _plan(
        reserved_ids={"import-chaos-0001", "import-chaos-0001-1", "import-chaos-0002"},
        reserved_paths={"library/import-chaos", "library/import-chaos-1/poster.jpg"},
    )
    assert events[0]["id"] == "import-chaos-0001-2"
    assert events[1]["id"] != "import-chaos-0002"
    destinations = [str(event["to"]) for event in events if "to" in event]
    assert len(destinations) == len(set(destinations))
    assert all(
        PurePosixPath(p).parent == PurePosixPath("library/import-chaos-2") for p in destinations
    )
    assert all(p.endswith((".mkv", ".flac")) for p in destinations)
    assert all(event["offset"] == "1s" for event in events if event["action"] == "touch_mtime")


@pytest.mark.parametrize(("seed", "count"), [(-1, 1), (0, 0), (0, 1001)])
def test_import_mutations_reject_unbounded_options(seed: int, count: int) -> None:
    with pytest.raises(ValueError, match=r"seed.*event_count"):
        _plan(seed=seed, event_count=count)


def test_import_mutations_require_surviving_assets() -> None:
    with pytest.raises(ValueError, match="asset"):
        _plan(assets=[])
