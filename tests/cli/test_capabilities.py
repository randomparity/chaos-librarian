"""Layer 5 — capabilities CLI integration tests with detect mocked."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from chaos_librarian.cli import commands as commands_pkg
from chaos_librarian.cli.app import app
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.contract.content_sources import ContentSourceCapabilities

# Patch detect_capabilities at the call site (cli.commands.capabilities)
# after the cli/app.py split (#23).
app_mod = commands_pkg.capabilities

runner = CliRunner()


def _caps(*, all_ok: bool = True) -> Capabilities:
    ffmpeg = ToolStatus(
        found=True,
        version="7.1.1",
        path="/x/ffmpeg",
        meets_minimum=all_ok,
    )
    ffprobe = ToolStatus(
        found=True,
        version="7.1.1",
        path="/x/ffprobe",
        meets_minimum=all_ok,
    )
    return Capabilities(
        schema_version=2,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test-arch",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=all_ok,
            materialize_filesystem_mutations=all_ok,
            materialize_media_mutations=False,
        ),
    )


def test_capabilities_exit_zero_on_minimum_met(monkeypatch):
    """WHY: agents read `capabilities --json` to decide whether to attempt
    materialize. Exit 0 with a JSON payload (Capabilities round-trip
    compatible) is the spec contract."""
    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=True))
    result = runner.invoke(app, ["capabilities", "--json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    Capabilities.model_validate(payload)
    assert payload["ready_for"]["materialize_static"] is True


def test_capabilities_exit_four_when_ffmpeg_missing(monkeypatch):
    """WHY: a regressed toolchain must surface as exit 4 with the same
    JSON payload — humans and agents see the structured reason regardless
    of exit code."""
    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=False))
    result = runner.invoke(app, ["capabilities", "--json"])
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ready_for"]["materialize_static"] is False


def test_capabilities_human_output_formats_each_tool(monkeypatch):
    """WHY: the human output must list every tool the design contract names
    (ffmpeg, ffprobe, mkvtoolnix), so operators reading the terminal can spot
    a missing or below-minimum tool without flipping to ``--json``."""
    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=True))
    result = runner.invoke(app, ["capabilities"])
    assert result.exit_code == 0
    assert "ffmpeg" in result.stdout
    assert "ffprobe" in result.stdout
    assert "mkvtoolnix" in result.stdout
