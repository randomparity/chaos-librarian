"""Engine tests for the podcast hierarchy and its timeline actions."""

from __future__ import annotations

import uuid
from typing import Any

from chaos_librarian.contract.journal import AtomicJournalEntry
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _engine_event_context

_RUN_ID = uuid.UUID("87654321-4321-6789-4321-678987654321")


def _episode_payload(
    episode_id: str,
    published_at: str,
    slug: str,
    *,
    stale: bool = False,
) -> dict[str, object]:
    return {
        "id": episode_id,
        "title": "Pilot",
        "published_at": published_at,
        "slug": slug,
        "stale": stale,
        "variants": [
            {
                "id": f"variant_{episode_id}",
                "label": "default",
                "bundle": {
                    "id": f"bundle_{episode_id}",
                    "assets": [
                        {
                            "id": f"asset_{episode_id}",
                            "role": "main",
                            "container": "mp3",
                            "duration_seconds": 60,
                            "audio": [{"codec": "mp3", "channels": "stereo", "language": "eng"}],
                            "subtitles": [],
                        }
                    ],
                },
            }
        ],
    }


def _podcast_scenario(
    timeline: list[dict[str, object]],
    *,
    episodes: list[dict[str, object]] | None = None,
) -> Scenario:
    if episodes is None:
        episodes = [_episode_payload("episode_1", "2026-05-01T00:00:00Z", "pilot")]
    return Scenario.model_validate(
        {
            "schema_version": 31,
            "scenario_id": "podcast-engine",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "pods", "path": "library/podcasts"}]},
            "movies": [],
            "series": [],
            "artists": [],
            "podcasts": [
                {
                    "id": "podcast_1",
                    "title": "The Daily",
                    "layout": "podcast_folder",
                    "episode_naming": "date_slug_title",
                    "episodes": episodes,
                }
            ],
            "timeline": timeline,
        }
    )


def _apply_timeline(scenario: Scenario) -> tuple[Any, ...]:
    ids = IdAllocator(TraceRecorder())
    state = build_initial_state(scenario, ids)
    entries: list[object] = []
    for resolved in resolve_timeline(scenario):
        entries.extend(
            apply_event(
                state=state,
                resolved=resolved,
                ids=ids,
                ctx=_engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
            )
        )
    return state, *entries


def test_initial_state_seeds_podcast_episode_location_and_rows() -> None:
    scenario = _podcast_scenario([])
    manifest = build_initial_state(scenario, IdAllocator(TraceRecorder())).to_manifest()

    assert manifest.podcasts[0].id == "podcast_1"
    assert manifest.podcast_episodes[0].id == "episode_1"
    assert manifest.podcast_episodes[0].stale is False
    assert any(
        loc.path == "library/podcasts/The Daily/2026-05-01 - pilot - Pilot - default.mp3"
        for loc in manifest.locations
    )


def test_republish_episode_rerenders_path_and_clears_stale() -> None:
    scenario = _podcast_scenario(
        [
            {
                "id": "t1",
                "at": "1s",
                "action": "republish_episode",
                "target": "episode_1",
                "published_at": "2026-06-02T00:00:00Z",
                "slug": "rerun",
            }
        ],
        episodes=[_episode_payload("episode_1", "2026-05-01T00:00:00Z", "pilot", stale=True)],
    )

    state, *_entries = _apply_timeline(scenario)
    manifest = state.to_manifest()

    episode = next(e for e in manifest.podcast_episodes if e.id == "episode_1")
    assert episode.stale is False
    assert any("2026-06-02 - rerun" in loc.path for loc in manifest.locations)


def test_mark_episode_stale_records_neutral_delta_and_keeps_path() -> None:
    scenario = _podcast_scenario(
        [{"id": "t1", "at": "1s", "action": "mark_episode_stale", "target": "episode_1"}]
    )

    state, *entries = _apply_timeline(scenario)
    manifest = state.to_manifest()

    episode = next(e for e in manifest.podcast_episodes if e.id == "episode_1")
    assert episode.stale is True
    location = next(loc for loc in manifest.locations if loc.asset_id == "asset_episode_1")
    assert location.path == "library/podcasts/The Daily/2026-05-01 - pilot - Pilot - default.mp3"
    stale_entries = [
        entry
        for entry in entries
        if isinstance(entry, AtomicJournalEntry) and entry.action == "mark_episode_stale"
    ]
    assert stale_entries
    assert stale_entries[0].state_delta["stale"] is True
