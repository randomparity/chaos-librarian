"""Shared fixtures for ``tests/validation/rules/``.

Exposes one factory fixture (``minimal_scenario``) plus three tiny helpers
(``empty_index``, ``as_list``, ``as_dict``). Every per-rule test module
draws from this conftest via pytest's auto-injection — no cross-test
imports needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from chaos_librarian.scenario_io import LineIndex

ListNarrower = Callable[[object], list[dict[str, object]]]
DictNarrower = Callable[[object], dict[str, object]]
ScenarioBuilder = Callable[..., dict[str, object]]


@pytest.fixture
def empty_index() -> LineIndex:
    """A fresh empty ``LineIndex`` for tests that don't drive the line-mapping."""
    return LineIndex()


@pytest.fixture
def as_list() -> ListNarrower:
    """Narrow ``object`` to a typed list for test-site subscripting.

    The scenario tree returned by ``minimal_scenario`` types everything as
    ``object`` (matching what semantic rules see). Tests know the concrete
    shape and use this fixture to drill in without sprinkling casts.
    """

    def _narrow(node: object) -> list[dict[str, object]]:
        return cast("list[dict[str, object]]", node)

    return _narrow


@pytest.fixture
def as_dict() -> DictNarrower:
    """Narrow ``object`` to a typed dict; mirror of ``as_list``."""

    def _narrow(node: object) -> dict[str, object]:
        return cast("dict[str, object]", node)

    return _narrow


@pytest.fixture
def minimal_scenario() -> ScenarioBuilder:
    """Factory: build a minimal valid-shape scenario. Overrides can add duplicates."""

    def _build(
        timeline: list[dict[str, object]] | None = None,
        asset_id: str = "a",
        asset_subtitles: list[dict[str, object]] | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        asset: dict[str, object] = {
            "id": asset_id,
            "role": "primary_video",
            "container": "mkv",
            "duration_seconds": 1,
        }
        if asset_subtitles is not None:
            asset["subtitles"] = asset_subtitles
        base: dict[str, object] = {
            "schema_version": 11,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r", "path": "r"}]},
            "works": [
                {
                    "id": "w",
                    "title": "t",
                    "variants": [
                        {
                            "id": "v",
                            "label": "l",
                            "bundle": {
                                "id": "b",
                                "assets": [asset],
                            },
                        }
                    ],
                }
            ],
            "timeline": timeline or [],
        }
        base.update(overrides)
        return base

    return _build
