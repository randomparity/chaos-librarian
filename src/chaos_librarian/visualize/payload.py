"""Assemble the JSON payload embedded into the visualizer HTML."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.visualize.diff import build_diffs
from chaos_librarian.visualize.replay import ReplayResult, replay_with_snapshots

_LOGGER = logging.getLogger(__name__)


def _rows(snapshot: dict[str, object], name: str) -> list[dict[str, object]]:
    """Return the named collection from a manifest snapshot dump.

    Args:
        snapshot: A ``model_dump`` dict typed as ``dict[str, object]``.
        name: Collection name (e.g. ``"assets"``).

    Returns:
        The collection rows, or an empty list if absent or not a list.
    """
    value = snapshot.get(name, [])
    if not isinstance(value, list):
        return []
    return cast("list[dict[str, object]]", value)


def _probed_final(run_dir: Path, final_snapshot: dict[str, object]) -> dict[str, object] | None:
    """Map asset_id → probed media from manifest.current.json, if present.

    Probed entries whose asset_id is absent from the final replayed snapshot
    are dropped with a warning (they indicate a manifest from a different run).
    Returns None when manifest.current.json is absent or carries no probed data.

    Args:
        run_dir: A scenario run directory.
        final_snapshot: The last replayed manifest snapshot.

    Returns:
        A dict mapping asset_id to serialized probed data, or ``None``.
    """
    current_path = run_dir / "manifest.current.json"
    if not current_path.exists():
        return None
    try:
        current = Manifest.model_validate_json(current_path.read_text())
    except ValidationError:
        _LOGGER.warning(
            "ignoring malformed manifest.current.json in %s; probed-final section omitted",
            run_dir,
        )
        return None
    final_assets = {str(asset["id"]) for asset in _rows(final_snapshot, "assets")}
    probed: dict[str, object] = {}
    for version in current.versions:
        if version.probed is None:
            continue
        if version.asset_id not in final_assets:
            _LOGGER.warning(
                "dropping probed data for asset_id %r: not in the final replayed "
                "snapshot (manifest.current.json may be from a different run)",
                version.asset_id,
            )
            continue
        probed[version.asset_id] = version.probed.model_dump(mode="json", exclude_none=True)
    return probed or None


def _events_payload(result: ReplayResult) -> list[dict[str, object]]:
    """Serialize events, tagging each with whether it was executed on disk.

    Args:
        result: The replay result containing events and live count.

    Returns:
        A list of serialized event dicts, each augmented with ``executed``.
    """
    out: list[dict[str, object]] = []
    for index, entry in enumerate(result.events):
        dumped = entry.model_dump(mode="json", exclude_none=True)
        dumped["executed"] = index < result.live_count
        out.append(dumped)
    return out


def build_payload(run_dir: Path) -> dict[str, object]:
    """Build the full visualizer payload for a run directory.

    Args:
        run_dir: A scenario run directory.

    Returns:
        A JSON-serializable dict with ``meta``, ``snapshots``, ``events``,
        ``diffs``, and ``probed_final``.

    Raises:
        MissingArtifactError: a required artifact is absent.
        ScenarioRevalidationError: the embedded scenario fails re-validation.
        JournalCorruptLineError: a non-final journal line is unparseable.
        JournalDivergenceError: the on-disk journal disagrees with replay.
    """
    result = replay_with_snapshots(run_dir)
    diffs = build_diffs(result.snapshots)
    warnings: list[str] = []
    if result.ended_mid_write:
        warnings.append("journal ended mid-write; final torn line dropped")
    return {
        "meta": {
            "scenario_id": result.scenario_id,
            "run_id": result.run_id,
            "execution_mode": result.execution_mode,
            "live_count": result.live_count,
            "total_events": result.total_events,
            "ended_mid_write": result.ended_mid_write,
            "warnings": warnings,
        },
        "snapshots": result.snapshots,
        "events": _events_payload(result),
        "diffs": diffs,
        "probed_final": _probed_final(run_dir, result.snapshots[-1]),
    }
