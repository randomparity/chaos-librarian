"""Per-step entity diffs between adjacent manifest snapshots.

Diffs are computed at the location / version / sidecar level. Because
``to_manifest`` re-renders every location's ``path`` from current hierarchy
state, an indirect change (e.g. a ``renumber_episode`` that moves an episode
file) surfaces here as a location ``path`` change even though its journal entry
targets a hierarchy entity — this is what lets the viewer's per-file Timeline
include indirect changes.

Scope note (deliberate v1 boundary, matches the spec's Tab-2 definition):
the per-file Timeline is keyed to changes that alter a file's path, content
hash, or sidecars — the location/version/sidecar collections. A pure
metadata/numbering change that does NOT move the file (e.g. a renumber under a
layout that doesn't embed the number in the filename, or ``mark_episode_stale``
flipping a ``podcast_episodes`` flag) produces a journal entry but no
diff-tracked change, so it is intentionally absent from that file's Timeline.
Such events remain visible globally as strip ticks and in the header's action
label when scrubbed to. Surfacing metadata-only lineage changes per-file is a
documented follow-up, not v1.
"""

from __future__ import annotations

from itertools import pairwise
from typing import cast

_COLLECTIONS = ("locations", "versions", "sidecars")


def _index(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["id"]): row for row in rows}


def _rows(snapshot: dict[str, object], name: str) -> list[dict[str, object]]:
    """Return the named collection from a manifest snapshot dump.

    The snapshot is a ``model_dump`` dict typed as ``dict[str, object]``;
    its collection values are always JSON arrays of row dicts.
    """
    value = snapshot.get(name, [])
    if not isinstance(value, list):
        return []
    return cast("list[dict[str, object]]", value)


def _diff_collection(
    prev_rows: list[dict[str, object]],
    curr_rows: list[dict[str, object]],
) -> dict[str, object]:
    """Compute added/removed/changed ids between two indexed collections."""
    prev, curr = _index(prev_rows), _index(curr_rows)
    added = sorted(curr.keys() - prev.keys())
    removed = sorted(prev.keys() - curr.keys())
    changed: list[dict[str, object]] = []
    for row_id in sorted(curr.keys() & prev.keys()):
        before, after = prev[row_id], curr[row_id]
        if before == after:
            continue
        fields = sorted(
            key for key in set(before) | set(after) if before.get(key) != after.get(key)
        )
        changed.append({"id": row_id, "fields": fields, "from": before, "to": after})
    return {"added": added, "removed": removed, "changed": changed}


def diff_snapshots(
    prev: dict[str, object], curr: dict[str, object]
) -> dict[str, dict[str, object]]:
    """Diff two manifest snapshots at the location/version/sidecar level.

    Args:
        prev: Manifest dump before the step.
        curr: Manifest dump after the step.

    Returns:
        A dict keyed by collection name, each holding ``added``/``removed``
        (sorted id lists) and ``changed`` (id + differing fields + from/to).
    """
    result: dict[str, dict[str, object]] = {}
    for name in _COLLECTIONS:
        result[name] = _diff_collection(_rows(prev, name), _rows(curr, name))
    return result


def build_diffs(snapshots: list[dict[str, object]]) -> list[dict[str, dict[str, object]]]:
    """Return one diff per snapshot transition (``len(snapshots) - 1`` entries).

    Args:
        snapshots: Per-entry manifest dumps from ``replay_with_snapshots``.

    Returns:
        A list of per-step diffs; ``diffs[i]`` describes the change from
        ``snapshots[i]`` to ``snapshots[i + 1]``.
    """
    return [diff_snapshots(prev, curr) for prev, curr in pairwise(snapshots)]
