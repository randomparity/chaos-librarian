"""Engine tests for the podcast hierarchy and its timeline actions."""

from __future__ import annotations

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.state import build_initial_state


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
            "schema_version": 30,
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
