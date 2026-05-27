"""Tests for materializer/sidecar_bytes.py — pure byte/argv generators."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.materializer.phase_b.sidecar_bytes import (
    perturbed_seed_for_update,
    poster_ffmpeg_argv,
    regenerate_sidecar,
    render_nfo,
)


def test_render_nfo_is_xml_with_sidecar_id():
    body = render_nfo(sidecar_id="sidecar_0001")
    assert body.startswith(b"<?xml")
    assert b"sidecar_0001" in body


def test_render_nfo_deterministic():
    a = render_nfo(sidecar_id="sidecar_0001")
    b = render_nfo(sidecar_id="sidecar_0001")
    assert a == b


def test_poster_ffmpeg_argv_uses_lavfi_color_source():
    argv = poster_ffmpeg_argv(
        output_path=Path("/tmp/x.png"),
        resolved_seed=42,
        sidecar_id="sidecar_0001",
    )
    assert argv[0] == "ffmpeg"
    assert "-f" in argv
    assert "lavfi" in argv
    # Hex color derived from seed should appear in the lavfi expression.
    joined = " ".join(argv)
    assert "color=" in joined
    assert "/tmp/x.png" in argv


def test_poster_ffmpeg_argv_deterministic_per_seed():
    a = poster_ffmpeg_argv(output_path=Path("/tmp/x.png"), resolved_seed=42, sidecar_id="s0")
    b = poster_ffmpeg_argv(output_path=Path("/tmp/x.png"), resolved_seed=42, sidecar_id="s0")
    assert a == b


def test_regenerate_sidecar_subtitle_returns_srt_bytes():
    """WHY: the SRT body must come from recipes.srt_payload with a
    perturbed sub-seed that incorporates sidecar_id+event_id (spec #7),
    so the rendered bytes must contain ``seed=<perturbed_seed>`` — not
    the raw resolved_seed. This proves update_sidecar uses the perturbed
    seed rather than collapsing to the resolved run seed."""
    expected_seed = perturbed_seed_for_update(
        sidecar_id="sidecar_0001",
        event_id="ev_us_001",
        resolved_seed=42,
    )
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
    )
    assert argv is None
    assert bytes_ is not None
    assert b"00:00:00,000" in bytes_  # SRT timestamp marker
    assert f"seed={expected_seed}".encode() in bytes_  # perturbed seed in body


def test_regenerate_sidecar_subtitle_remains_default_utf8_srt() -> None:
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
    )

    assert argv is None
    assert bytes_ is not None
    assert bytes_.startswith(b"1\n")
    assert b"[Script Info]" not in bytes_


def test_regenerate_sidecar_subtitle_distinct_per_event_id():
    a_bytes, _ = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_a",
        duration_s=1.0,
    )
    b_bytes, _ = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_b",
        duration_s=1.0,
    )
    assert a_bytes != b_bytes  # event_id is in the perturbed seed


def test_regenerate_sidecar_nfo_returns_xml_bytes():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.NFO,
        language=None,
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
    )
    assert argv is None
    assert bytes_ is not None
    assert bytes_.startswith(b"<?xml")


def test_regenerate_sidecar_poster_returns_argv():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.POSTER,
        language=None,
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
        output_path=Path("/tmp/x.png"),
    )
    assert bytes_ is None
    assert argv is not None
    assert argv[0] == "ffmpeg"
