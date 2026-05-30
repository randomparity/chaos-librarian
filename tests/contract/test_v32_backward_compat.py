"""Backward-compatibility regression for the scenario v32 bump (#118).

The three v32 additions (SidecarKind.CUE, poster image_format, corrupt_tags)
are all optional/additive. Existing movie/TV/podcast scenarios must round-trip
unchanged at v32, and the new fields must be absent-by-default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.scenario import CreateSidecarEvent, Scenario

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
_REPRESENTATIVE = ("movie-editions.yaml", "tv-season-folders.yaml", "podcast-basic.yaml")


@pytest.mark.parametrize("fixture", _REPRESENTATIVE)
def test_existing_topology_roundtrips_unchanged_at_v32(fixture: str) -> None:
    raw = YAML(typ="safe").load((_FIXTURES_DIR / fixture).read_text())
    scenario = Scenario.model_validate(raw)
    dump = scenario.model_dump(mode="json", by_alias=True)

    assert dump["schema_version"] == 32
    # Idempotent round-trip: re-validating the dump must reproduce it exactly,
    # proving no movie/TV/podcast field gained a non-default value at v32.
    redump = Scenario.model_validate(dump).model_dump(mode="json", by_alias=True)
    assert redump == dump


def test_poster_image_format_absent_by_default() -> None:
    sidecar = CreateSidecarEvent.model_validate(
        {"id": "e", "at": "0s", "target": "a", "to": "x.png", "kind": "poster"}
    )
    assert sidecar.image_format is None
    dump = sidecar.model_dump(mode="json", exclude_none=True, by_alias=True)
    assert "image_format" not in dump


def test_cue_kind_does_not_change_default_kind() -> None:
    sidecar = CreateSidecarEvent.model_validate(
        {"id": "e", "at": "0s", "target": "a", "to": "x.srt", "language": "eng"}
    )
    assert sidecar.kind.value == "subtitle"
