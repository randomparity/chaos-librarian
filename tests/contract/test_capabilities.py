"""Contract round-trip tests for Capabilities."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.contract.content_sources import (
    ContentSourceCapabilities,
    ContentSourceProviderCapability,
)


def _ok_tool(version: str = "7.1.1", path: str = "/usr/bin/ffmpeg") -> ToolStatus:
    return ToolStatus(found=True, version=version, path=path, meets_minimum=True)


def _content_source_caps() -> ContentSourceCapabilities:
    return ContentSourceCapabilities(
        providers=[
            ContentSourceProviderCapability(
                name="builtin-lavfi",
                available=True,
                requires_network=False,
                requires_cache=False,
                required_tool="ffmpeg",
                sources=("video:color_bars",),
            )
        ]
    )


def test_capabilities_round_trip():
    """WHY: external consumers parse this JSON via their own JSON Schema
    consumer; a round-trip with exclude_none=True is the contract."""
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=_ok_tool(),
        ffprobe=_ok_tool(path="/usr/bin/ffprobe"),
        mkvtoolnix=ToolStatus(found=False, version=None, path=None, meets_minimum=False),
        platform="darwin-arm64",
        content_sources=_content_source_caps(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ),
    )
    payload = caps.model_dump_json(indent=2, exclude_none=True)
    loaded = Capabilities.model_validate_json(payload)
    assert loaded == caps
    assert loaded.content_sources.providers[0].name == "builtin-lavfi"


def test_tool_status_optional_fields_omitted_when_none():
    """WHY: when a tool is not found, version/path must serialize as None
    (or be absent under exclude_none) — not as empty strings."""
    tool = ToolStatus(found=False, version=None, path=None, meets_minimum=False)
    rendered = json.loads(tool.model_dump_json(exclude_none=True))
    assert rendered == {"found": False, "meets_minimum": False}


def test_capabilities_schema_version_pinned():
    missing_tool = ToolStatus(found=False, version=None, path=None, meets_minimum=False)
    payload = {
        "schema_version": 99,
        "ffmpeg": _ok_tool().model_dump(),
        "ffprobe": _ok_tool(path="/usr/bin/ffprobe").model_dump(),
        "mkvtoolnix": missing_tool.model_dump(),
        "platform": "darwin-arm64",
        "content_sources": _content_source_caps().model_dump(),
        "ready_for": ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ).model_dump(),
    }
    with pytest.raises(ValidationError):
        Capabilities.model_validate(payload)
