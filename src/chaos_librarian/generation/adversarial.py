"""Bounded authored recipes for the explicit adversarial-media generation lane."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from chaos_librarian.contract.scenario import (
    Asset,
    CorruptContainerHeaderEvent,
    CreateSidecarEvent,
    EditMetadataEvent,
    Scenario,
    TruncateFileEvent,
)
from chaos_librarian.topology import iter_asset_contexts

FLAG_CASES = {
    "multiple": (True, False, 2),
    "none": (False, False, 2),
    "default_forced": (True, True, 2),
    "forced_only": (False, True, 8),
}
METADATA_CASES = {
    "title": {"title": "Embedded title"},
    "year": {"year": "9999"},
    "long": {"title": "雪" * 1365 + "x"},
    "control": {"title": "雪 café\tline\nnext"},
    "delete": {"title": "", "year": ""},
}
REQUIRED_CELLS = frozenset(
    ["adversarial:flags:" + name for name in FLAG_CASES]
    + ["adversarial:metadata:" + name for name in (*METADATA_CASES, "missing", "languages")]
    + [
        "adversarial:structural:" + name
        for name in ("mp4-moov_at_start", "mp4-moov_at_end", "mkv-cues", "mp3-16-frames")
    ]
)


def _asset(asset_id: str, container: str = "mkv") -> dict[str, object]:
    payload: dict[str, object] = {
        "id": asset_id,
        "role": "primary_audio" if container == "mp3" else "main",
        "container": container,
        "duration_seconds": 2,
        "audio": [
            {
                "source": "sine",
                "codec": "mp3" if container == "mp3" else "aac",
                "channels": "stereo",
                "language": "eng",
                "sample_rate": 44100,
            }
        ],
    }
    if container != "mp3":
        payload["video"] = {"source": "color_bars", "codec": "h264", "resolution": "sd"}
    return payload


def assets() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, (default, forced, count) in FLAG_CASES.items():
        asset = _asset("flags_" + name)
        asset["duration_seconds"] = 0.2
        asset["audio"] = [
            {
                "codec": "aac",
                "channels": "stereo",
                "language": "eng",
                "role": "commentary" if index == 0 else "main",
                "default": default,
                "forced": forced,
            }
            for index in range(count)
        ]
        asset["subtitles"] = [
            {
                "codec": "srt",
                "language": "eng",
                "mode": "embedded",
                "default": default,
                "forced": forced,
            }
            for _ in range(count)
        ]
        result.append(asset)
    for name in (*METADATA_CASES, "missing", "languages"):
        asset = _asset("metadata_" + name)
        if name == "languages":
            asset["audio"] = [
                {"codec": "aac", "channels": "stereo", "language": language}
                for language in ("eng", "fra")
            ]
        result.append(asset)
    for name, container, placement in (
        ("damage_mp4_start", "mp4", "moov_at_start"),
        ("damage_mp4_end", "mp4", "moov_at_end"),
        ("damage_mkv", "mkv", None),
        ("control_mp4", "mp4", "moov_at_end"),
        ("control_mkv", "mkv", None),
        ("damage_mp3", "mp3", None),
        ("control_mp3", "mp3", None),
    ):
        asset = _asset(name, container)
        if placement is not None:
            asset["mp4_moov_placement"] = placement
        result.append(asset)
    return result


def events() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for name, fields in METADATA_CASES.items():
        if name == "delete":
            result.append(
                {
                    "action": "edit_metadata",
                    "target": "metadata_delete",
                    "fields": {"title": "Title to delete", "year": "2026"},
                }
            )
        result.append({"action": "edit_metadata", "target": "metadata_" + name, "fields": fields})
        if name == "title":
            result.append(
                {
                    "action": "create_sidecar",
                    "target": "metadata_title",
                    "kind": "nfo",
                    "to": "movies/Disagreement.nfo",
                    "body": "<movie><title>Sidecar title</title></movie>",
                }
            )
    for target, region in (
        ("damage_mp4_start", "mp4_moov"),
        ("damage_mp4_end", "mp4_moov"),
        ("damage_mkv", "mkv_cues"),
    ):
        result.append({"action": "corrupt_container_header", "target": target, "region": region})
    result.append(
        {"action": "truncate_file", "target": "damage_mp3", "boundary": "mp3_after_16_frames"}
    )
    for index, event in enumerate(result, 1):
        event.update(id=f"adversarial_{index:02d}", at=f"{index}ns")
    return result


def payload_parts(
    seed: int,
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    video_variants: list[dict[str, object]] = []
    tracks: list[dict[str, object]] = []
    for asset in assets():
        asset_id = str(asset["id"])
        variant: dict[str, object] = {
            "id": "variant_" + asset_id,
            "label": asset_id,
            "bundle": {"id": "bundle_" + asset_id, "assets": [asset]},
        }
        if asset["container"] == "mp3":
            tracks.append(
                {
                    "id": "track_" + asset_id,
                    "track_number": len(tracks) + 1,
                    "title": asset_id,
                    "variants": [variant],
                }
            )
        else:
            video_variants.append(variant)
    movies: list[dict[str, object]] = [
        {
            "id": "adversarial_movie",
            "title": f"Filename {seed}",
            "layout": "movie_flat",
            "variants": video_variants,
        }
    ]
    artists: list[dict[str, object]] = [
        {
            "id": "adversarial_artist",
            "name": "Synthetic controls",
            "layout": "artist_album_flat",
            "track_naming": "track_number_title",
            "albums": [
                {
                    "id": "adversarial_album",
                    "title": "Structural MP3",
                    "discs": [{"id": "adversarial_disc", "disc_number": 1, "tracks": tracks}],
                }
            ],
        }
    ]
    return (
        {"roots": [{"id": "movies-hd", "path": "movies"}, {"id": "music", "path": "music"}]},
        movies,
        [],
        artists,
        events(),
    )


def _flag_cells(asset: Asset) -> set[str]:
    cells: set[str] = set()
    for name, (default, forced, count) in FLAG_CASES.items():
        tracks = (*asset.audio, *asset.subtitles)
        if (
            len(asset.audio) == len(asset.subtitles) == count
            and asset.audio[0].role.value == "commentary"
            and all((t.default, t.forced) == (default, forced) for t in tracks)
            and all(t.mode.value == "embedded" for t in asset.subtitles)
        ):
            cells.add("adversarial:flags:" + name)
    return cells


def _metadata_cells(scenario: Scenario, by_id: dict[str, Asset]) -> set[str]:
    cells: set[str] = set()
    prior_fields: dict[str, dict[str, str]] = {}
    edited: set[str] = set()
    nfo_targets = {
        e.target
        for e in scenario.timeline
        if isinstance(e, CreateSidecarEvent)
        and e.kind.value == "nfo"
        and e.body is not None
        and "Sidecar title" in e.body
    }
    for event in scenario.timeline:
        if not isinstance(event, EditMetadataEvent):
            continue
        prior = prior_fields.setdefault(event.target, {})
        for name, fields in METADATA_CASES.items():
            if (
                event.fields == fields
                and (name != "delete" or all(prior.get(k) for k in fields))
                and (name != "title" or event.target in nfo_targets)
            ):
                cells.add("adversarial:metadata:" + name)
        prior.update(event.fields)
        edited.add(event.target)
    if any(a.container == "mkv" and a.id not in edited and not a.subtitles for a in by_id.values()):
        cells.add("adversarial:metadata:missing")
    if any([t.language for t in a.audio] == ["eng", "fra"] for a in by_id.values()):
        cells.add("adversarial:metadata:languages")
    return cells


def _structural_cells(scenario: Scenario, by_id: dict[str, Asset]) -> set[str]:
    cells: set[str] = set()
    for event in scenario.timeline:
        if isinstance(event, CorruptContainerHeaderEvent):
            asset = by_id.get(event.target)
            if asset is None:
                continue
            if event.region == "mp4_moov" and asset.mp4_moov_placement is not None:
                cells.add("adversarial:structural:mp4-" + asset.mp4_moov_placement.value)
            elif event.region == "mkv_cues":
                cells.add("adversarial:structural:mkv-cues")
        elif isinstance(event, TruncateFileEvent) and event.boundary == "mp3_after_16_frames":
            cells.add("adversarial:structural:mp3-16-frames")
    return cells


def coverage_cells(payload: Mapping[str, object]) -> frozenset[str]:
    # Other coverage primitives intentionally also accept partial payloads.
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError:
        return frozenset()
    by_id = {c.asset.id: c.asset for c in iter_asset_contexts(scenario)}
    cells = _metadata_cells(scenario, by_id) | _structural_cells(scenario, by_id)
    for asset in by_id.values():
        cells.update(_flag_cells(asset))
    return frozenset(cells)
