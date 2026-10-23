"""Real path-shape materialization/replay: names, bytes and links are evidence."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities

RECIPE = Path(__file__).resolve().parents[2] / "recipes/scanner/path-shapes.yaml"

runner = CliRunner()
pytestmark = [
    pytest.mark.skipif(os.name != "posix", reason="path-shape corpus requires UTF-8 POSIX"),
    pytest.mark.skipif(
        not detect_capabilities().ready_for.materialize_static,
        reason="path-shape real proof requires ffmpeg/ffprobe >=7",
    ),
]


def test_path_shapes_materialize_and_replay(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    name_max = os.pathconf(tmp_path, "PC_NAME_MAX")
    path_max = os.pathconf(tmp_path, "PC_PATH_MAX")
    request.node.user_properties.extend([("PC_NAME_MAX", name_max), ("PC_PATH_MAX", path_max)])
    if 0 < name_max < 250 or 0 < path_max < len(os.fsencode(tmp_path)) + 700:
        pytest.skip("filesystem limits do not support the 250-byte/700-byte path corpus")
    out = tmp_path / "source"
    result = runner.invoke(
        app, ["run", str(RECIPE), "--out", str(out), "--duration", "1s", "--speed", "1x", "--json"]
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    locations = {item["asset_id"]: item["path"] for item in manifest["locations"]}
    library = out / "library"
    entries = {str(path.relative_to(library)) for path in library.rglob("*") if path.is_file()}
    request.node.user_properties.append(("actual_path_spellings", json.dumps(sorted(entries))))
    for asset, intended in locations.items():
        assert (library / intended).is_file(), (asset, intended)
        if asset in {"asset_nfc", "asset_nfd", "asset_original", "asset_link"}:
            assert any(
                unicodedata.normalize("NFC", actual) == unicodedata.normalize("NFC", intended)
                for actual in entries
            )
        else:
            assert intended in entries
    assert len(Path(locations["asset_long"]).name.encode("utf-8")) == 250
    assert len(locations["asset_unicode"].encode("utf-8")) > len(locations["asset_unicode"])
    original = library / locations["asset_original"]
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    for intended in locations.values():
        assert hashlib.sha256((library / intended).read_bytes()).hexdigest() == digest
    link = library / locations["asset_link"]
    assert link.is_symlink()
    assert not Path(os.readlink(link)).is_absolute()
    assert link.resolve() == original.resolve()
    journal = [json.loads(line) for line in (out / "journal.jsonl").read_text().splitlines()]
    assert len(journal) == 9
    destinations = {entry["target_ids"][0]: entry["state_delta"]["to_path"] for entry in journal}
    assert destinations == {
        asset: path for asset, path in locations.items() if asset != "asset_original"
    }
    replay = tmp_path / "replay"
    result = runner.invoke(
        app,
        ["replay", str(out / "replay.json"), "--out", str(replay), "--against", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert json.loads((replay / "manifest.current.json").read_text()) == manifest
    replay_link = replay / "library" / locations["asset_link"]
    assert replay_link.is_symlink()
    assert os.readlink(replay_link) == os.readlink(link)
