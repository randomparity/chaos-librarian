"""Project a scenario's declared per-asset track layout.

Plan-only runs carry no ffprobe output: the viewer's snapshots come from the
plan engine path (``build_initial_state`` -> ``apply_event`` -> ``to_manifest``),
which never stamps ``version.probed`` -- that is a materializer artifact. The
scenario, however, fully declares each asset's intended ``video``/``audio``/
``subtitles``. This module projects that declaration into a JSON-serializable
map so the viewer can show the intended layout in every mode and diff it against
probed reality when a materialized run provides it.
"""

from __future__ import annotations

from chaos_librarian.contract.scenario import Asset, Scenario
from chaos_librarian.topology import iter_asset_contexts


def _row(kind: str, codec: object, language: str | None, detail: object) -> dict[str, object]:
    """Build one normalized track row.

    ``codec`` and ``detail`` may be ``StrEnum`` members (e.g. subtitle codec,
    audio channel layout); coerce them to plain strings so the payload is
    JSON-native.
    """
    return {"kind": kind, "codec": str(codec), "language": language, "detail": str(detail)}


def asset_track_rows(asset: Asset) -> list[dict[str, object]]:
    """Project one asset's declared tracks in stream order.

    Order is video, then audio, then subtitles -- matching how the materializer
    emits streams, so the renderer can pair these rows positionally against
    probed streams of the same kind.

    Args:
        asset: A scenario asset.

    Returns:
        Normalized track rows; empty when the asset declares no tracks.
    """
    rows: list[dict[str, object]] = []
    if asset.video is not None:
        rows.append(_row("video", asset.video.codec, None, asset.video.resolution))
    for track in asset.audio:
        rows.append(_row("audio", track.codec, track.language, track.channels))
    for track in asset.subtitles:
        rows.append(_row("subtitle", track.codec, track.language, track.mode))
    return rows


def declared_tracks_by_asset(scenario: Scenario) -> dict[str, list[dict[str, object]]]:
    """Map asset_id -> declared track rows for every asset that declares tracks.

    Args:
        scenario: The validated scenario.

    Returns:
        A dict keyed by asset id; assets with no declared tracks are omitted.
    """
    out: dict[str, list[dict[str, object]]] = {}
    for context in iter_asset_contexts(scenario):
        rows = asset_track_rows(context.asset)
        if rows:
            out[context.asset.id] = rows
    return out
