"""Shared sentinel and replay-bundle loaders for cli/commands.

Exposes the discriminated-union ``REPLAY_BUNDLE_ADAPTER`` (one
``TypeAdapter`` per process) plus sentinel/bundle file readers that
swallow missing-file and validation errors in favor of returning None,
which is the convention every caller wants.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle, ReplayBundle
from chaos_librarian.contract.run_sentinel import SENTINEL_FILENAME, RunSentinel

__all__ = [
    "REPLAY_BUNDLE_ADAPTER",
    "infer_original",
    "load_replay_bundle",
    "load_sentinel",
]


REPLAY_BUNDLE_ADAPTER: Final = TypeAdapter(ReplayBundle)


def infer_original(bundle_path: Path, run_id: uuid.UUID, applied_events: int) -> Path | None:
    """Return ``bundle_path.parent`` when it is the bundle's original fixture.

    Two bundles of the same scenario+seed at different truncation points share
    a ``run_id``; the cross-check on ``applied_events`` ensures auto-discover
    does not match a different-length sibling fixture. Returns ``None`` when
    the sentinel is missing, the sentinel is unparseable, the sibling
    ``replay.json`` is missing or unparseable, or either field disagrees.
    """
    parent = bundle_path.parent
    sentinel = load_sentinel(parent / SENTINEL_FILENAME)
    if sentinel is None or sentinel.run_id != run_id:
        return None
    parent_bundle = load_replay_bundle(parent / "replay.json")
    if parent_bundle is None or parent_bundle.applied_events != applied_events:
        return None
    return parent


def load_sentinel(path: Path) -> RunSentinel | None:
    """Parse a sentinel file, returning ``None`` when absent or malformed."""
    if not path.exists():
        return None
    try:
        return RunSentinel.model_validate_json(path.read_text())
    except ValidationError:
        return None


def load_replay_bundle(path: Path) -> PlanOnlyReplayBundle | None:
    """Parse a plan-only replay bundle, returning ``None`` when absent or malformed."""
    if not path.exists():
        return None
    try:
        return PlanOnlyReplayBundle.model_validate_json(path.read_text())
    except ValidationError:
        return None
