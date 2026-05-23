"""Layer 2 — capability detection with subprocess mocked at the boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

import pytest
from packaging.version import Version

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.materializer.errors import CapabilityGateError
from chaos_librarian.materializer.tooling import capabilities as cap_mod
from chaos_librarian.materializer.tooling.capabilities import (
    MIN_VERSIONS,
    _canonical_version_from_tool_output,
    assert_capable_for_static_materialize,
    detect_capabilities,
)

OK_FFMPEG: Final = "ffmpeg version 7.1.1 Copyright (c) 2000-2024 the FFmpeg developers"
OK_FFPROBE: Final = "ffprobe version 7.1.1 Copyright (c) 2000-2024 the FFmpeg developers"
OK_MKV: Final = "mkvmerge v80.0 ('Roundabout') 64-bit"
OLD_FFMPEG: Final = "ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers"


def _stub_subprocess_run(returns: dict[str, str]) -> object:
    """Build a subprocess.run stub indexed by argv[0]."""

    def stub(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        tool = Path(argv[0]).name
        stdout = returns.get(tool, "")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=stdout, stderr="")

    return stub


def _stub_which(paths: dict[str, str]) -> object:
    def stub(name: str) -> str | None:
        return paths.get(name)

    return stub


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7.1.1", Version("7.1.1")),
        ("n7.1-0ubuntu1", Version("7.1")),
        ("7.0.2-3ubuntu1", Version("7.0.2")),
        ("n7.0 Copyright (c) ...", Version("7.0")),
        ("6.1.1", Version("6.1.1")),
    ],
)
def test_canonical_version_accepts_distro_tagged_strings(raw: str, expected: Version) -> None:
    """WHY: Ubuntu packages ship versions like 'n7.1-0ubuntu1' which
    packaging.version.Version rejects raw; the helper must normalize so a
    working Ubuntu FFmpeg passes the gate."""
    assert _canonical_version_from_tool_output(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "N-118412-g0ce1c8f7c5 (git build)",
        "<garbage>",
        "",
    ],
)
def test_canonical_version_returns_none_on_malformed_input(raw: str) -> None:
    """WHY: git-snapshot builds and unparseable strings must be reported as
    found-but-malformed, not raise — the caller marks meets_minimum=False."""
    assert _canonical_version_from_tool_output(raw) is None


def test_detect_capabilities_all_present_above_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which(
            {
                "ffmpeg": "/usr/bin/ffmpeg",
                "ffprobe": "/usr/bin/ffprobe",
                "mkvmerge": "/usr/bin/mkvmerge",
            }
        ),
    )
    monkeypatch.setattr(
        cap_mod.subprocess,
        "run",
        _stub_subprocess_run({"ffmpeg": OK_FFMPEG, "ffprobe": OK_FFPROBE, "mkvmerge": OK_MKV}),
    )
    caps = detect_capabilities()
    assert caps.ffmpeg.meets_minimum
    assert caps.ffprobe.meets_minimum
    assert caps.mkvtoolnix.meets_minimum
    assert caps.ready_for.materialize_static
    assert caps.ready_for.materialize_media_mutations


def test_detect_capabilities_ffmpeg_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which({"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"}),
    )
    monkeypatch.setattr(
        cap_mod.subprocess,
        "run",
        _stub_subprocess_run({"ffmpeg": OLD_FFMPEG, "ffprobe": OK_FFPROBE}),
    )
    caps = detect_capabilities()
    assert caps.ffmpeg.found
    assert not caps.ffmpeg.meets_minimum
    assert not caps.ready_for.materialize_static


def test_detect_capabilities_mkvtoolnix_missing_static_still_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: Sprint 5's static materialize doesn't need mkvtoolnix; absent
    mkvmerge must not block materialize_static."""
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which({"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"}),
    )
    monkeypatch.setattr(
        cap_mod.subprocess,
        "run",
        _stub_subprocess_run({"ffmpeg": OK_FFMPEG, "ffprobe": OK_FFPROBE}),
    )
    caps = detect_capabilities()
    assert caps.ready_for.materialize_static
    assert not caps.ready_for.materialize_media_mutations
    assert not caps.mkvtoolnix.found


def test_detect_capabilities_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which({"ffmpeg": "/usr/bin/ffmpeg"}),
    )

    def raise_timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=5)

    monkeypatch.setattr(cap_mod.subprocess, "run", raise_timeout)
    caps = detect_capabilities()
    assert not caps.ffmpeg.meets_minimum
    assert caps.ffmpeg.version is None


def test_assert_capable_raises_on_regression() -> None:
    caps = Capabilities(
        schema_version=2,
        ffmpeg=ToolStatus(found=False, meets_minimum=False),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="darwin-arm64",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=False,
            materialize_filesystem_mutations=False,
            materialize_media_mutations=False,
        ),
    )
    with pytest.raises(CapabilityGateError):
        assert_capable_for_static_materialize(caps)


def test_min_versions_constant_matches_spec() -> None:
    assert MIN_VERSIONS["ffmpeg"] == Version("7.0")
    assert MIN_VERSIONS["ffprobe"] == Version("7.0")
    assert MIN_VERSIONS["mkvtoolnix"] == Version("80")
