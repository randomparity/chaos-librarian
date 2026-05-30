"""Tests for materializer/sidecar_bytes.py — pure byte/argv generators."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.materializer.phase_b.sidecar_bytes import (
    cue_payload,
    encode_subtitle_body,
    perturbed_seed_for_update,
    poster_ffmpeg_argv,
    regenerate_sidecar,
    render_nfo,
)


def test_encode_subtitle_default_is_utf8():
    assert encode_subtitle_body("héllo", None) == "héllo".encode()
    assert encode_subtitle_body("héllo", "utf8") == "héllo".encode()


def test_encode_subtitle_utf16_le():
    assert encode_subtitle_body("hi", "utf16_le") == "hi".encode("utf-16-le")


def test_encode_subtitle_utf8_bom():
    out = encode_subtitle_body("hi", "utf8_bom")
    assert out.startswith(b"\xef\xbb\xbf")
    assert out[3:] == b"hi"


def test_encode_subtitle_iso_8859_1():
    assert encode_subtitle_body("café", "iso_8859_1") == "café".encode("iso-8859-1")


def test_regenerate_subtitle_applies_encoding():
    bytes_, _ = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
        encoding="utf16_le",
    )
    assert bytes_ is not None
    decoded = bytes_.decode("utf-16-le")
    assert "00:00:00,000" in decoded


def test_regenerate_nfo_uses_authored_body():
    bytes_, _ = regenerate_sidecar(
        kind=SidecarKind.NFO,
        language=None,
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
        body="<movie>AUTHORED</movie>",
    )
    assert bytes_ == b"<movie>AUTHORED</movie>"


def test_regenerate_poster_video_media_type_changes_argv():
    _, image_argv = regenerate_sidecar(
        kind=SidecarKind.POSTER,
        language=None,
        sidecar_id="s0",
        resolved_seed=42,
        event_id="ev",
        duration_s=1.0,
        output_path=Path("/tmp/x.mkv"),
        media_type="image",
    )
    _, video_argv = regenerate_sidecar(
        kind=SidecarKind.POSTER,
        language=None,
        sidecar_id="s0",
        resolved_seed=42,
        event_id="ev",
        duration_s=1.0,
        output_path=Path("/tmp/x.mkv"),
        media_type="video",
    )
    assert image_argv is not None
    assert video_argv is not None
    assert image_argv != video_argv


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


def test_poster_argv_selects_webp_encoder():
    argv = poster_ffmpeg_argv(
        output_path=Path("/tmp/cover.webp"),
        resolved_seed=1,
        sidecar_id="sc-1",
        image_format="webp",
    )
    assert "libwebp" in argv


def test_poster_argv_selects_mjpeg_encoder():
    argv = poster_ffmpeg_argv(
        output_path=Path("/tmp/cover.jpg"),
        resolved_seed=1,
        sidecar_id="sc-1",
        image_format="jpeg",
    )
    assert "mjpeg" in argv


def test_poster_argv_default_image_omits_explicit_encoder():
    argv = poster_ffmpeg_argv(
        output_path=Path("/tmp/cover.png"),
        resolved_seed=1,
        sidecar_id="sc-1",
        image_format=None,
    )
    assert "libwebp" not in argv
    assert "mjpeg" not in argv


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


def test_cue_payload_uses_authored_body_verbatim():
    body = 'FILE "album.flac" WAVE\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n'
    assert cue_payload(body=body, sidecar_id="sc-1") == body.encode("utf-8")


def test_cue_payload_default_is_deterministic_and_nonempty():
    a = cue_payload(body=None, sidecar_id="sc-1")
    b = cue_payload(body=None, sidecar_id="sc-1")
    assert a == b
    assert a.startswith(b"PERFORMER ")
    assert b"TRACK 01 AUDIO" in a


def test_regenerate_sidecar_cue_uses_authored_body():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.CUE,
        language=None,
        sidecar_id="sc-1",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
        body='FILE "x.flac" WAVE\n  TRACK 01 AUDIO',
    )
    assert argv is None
    assert bytes_ == b'FILE "x.flac" WAVE\n  TRACK 01 AUDIO'


def test_regenerate_sidecar_cue_default_when_no_body():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.CUE,
        language=None,
        sidecar_id="sc-1",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
    )
    assert argv is None
    assert bytes_ is not None
    assert bytes_.startswith(b"PERFORMER ")
