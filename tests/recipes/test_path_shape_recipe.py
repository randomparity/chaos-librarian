"""The path corpus is a byte-budgeted scanner input, not merely valid YAML."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from chaos_librarian.generation.lanes import coverage_for_payload
from chaos_librarian.validation import prepare_run_input, run_validation

RECIPE = Path(__file__).resolve().parents[2] / "recipes/scanner/path-shapes.yaml"
REQUIRED = frozenset(
    {
        "path:unicode-basename",
        "path:unicode-parent",
        "path:nfc",
        "path:nfd",
        "path:long-component",
        "path:deep",
        "path:leading-dash",
        "path:whitespace",
        "path:metacharacters",
        "path:control",
    }
)


def test_recipe_paths_cover_the_matrix_without_media_variation() -> None:
    payload = YAML(typ="safe").load(RECIPE.read_text(encoding="utf-8"))
    report = run_validation(prepare_run_input(RECIPE))
    assert report.ok, report.issues
    assert coverage_for_payload(payload).cells >= REQUIRED
    paths = {event["target"]: event["to"] for event in payload["timeline"]}
    assert len(Path(paths["asset_long"]).name.encode("utf-8")) == 250
    assert 512 < len(paths["asset_deep"].encode("utf-8")) < 700
    assert len(Path(paths["asset_deep"]).parts) >= 10
    assert "\n" in paths["asset_control"]
    assert "\t" in paths["asset_control"]
    assert "  " in paths["asset_meta"]
    assert paths["asset_nfc"].endswith("café.mkv")
    assert paths["asset_nfd"].endswith("cafe\u0301.mkv")
    assets = [variant["bundle"]["assets"][0] for variant in payload["movies"][0]["variants"]]
    assert {asset["container"] for asset in assets} == {"mkv"}
    assert sum(asset.get("same_content_as") == "asset_original" for asset in assets) == 8
    assert assets[-1]["symlink"] == {"to_asset": "asset_original"}
