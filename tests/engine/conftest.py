"""Shared helpers for engine-level tests.

The ``_build_minimal_scenario`` factory below is used by multiple Sprint 6
test modules (``test_state.py`` for root/archive lookups, plus the
filesystem-event handler tests landing in later tasks) to spin up a
contract-valid ``Scenario`` without restating the full nested literal at
every call site.
"""

from __future__ import annotations

from chaos_librarian.contract.scenario import Scenario


def _build_minimal_scenario(
    *,
    roots: list[tuple[str, str]],
    works: list[tuple[str, str, str]],
    archive_root: str | None = None,
) -> Scenario:
    """Build a minimal Scenario for engine-level tests.

    Each ``works`` entry is ``(work_id, asset_id, container)``; the helper
    synthesizes one variant and one bundle per work, each holding the
    single declared asset. ``roots`` entries are ``(root_id, root_path)``;
    the first root is the primary one ``build_initial_state`` uses to
    synthesize initial location paths.

    The returned Scenario carries an empty timeline — these tests probe
    initial state only.

    Args:
        roots: declared library roots, in scenario order.
        works: one tuple per asset, each producing its own work / variant
            / bundle wrapper.
        archive_root: optional ``library.archive_root`` value. ``None``
            leaves the field at its default; the literal string
            ``"archive"`` is the sentinel meaning "default subdir of the
            primary root".

    Returns:
        A fully-validated Scenario at ``schema_version=4``.
    """
    library: dict[str, object] = {
        "roots": [{"id": root_id, "path": path} for root_id, path in roots],
    }
    if archive_root is not None:
        library["archive_root"] = archive_root

    scenario_works = [
        {
            "id": work_id,
            "title": work_id,
            "variants": [
                {
                    "id": f"variant_{work_id}",
                    "label": "default",
                    "bundle": {
                        "id": f"bundle_{work_id}",
                        "assets": [
                            {
                                "id": asset_id,
                                "role": "primary_video",
                                "container": container,
                                "duration_seconds": 1,
                            }
                        ],
                    },
                }
            ],
        }
        for work_id, asset_id, container in works
    ]

    return Scenario.model_validate(
        {
            "schema_version": 4,
            "scenario_id": "engine-test",
            "seed": 1,
            "duration_scale": "short",
            "library": library,
            "works": scenario_works,
            "timeline": [],
        }
    )
