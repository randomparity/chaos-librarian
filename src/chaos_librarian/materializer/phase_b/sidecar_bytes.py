"""Byte generators for non-subtitle sidecars + update_sidecar regeneration.

- ``render_nfo``: pure Python XML template. Returns bytes.
- ``poster_ffmpeg_argv``: returns the ffmpeg argv that will write a
  PNG via lavfi color source. The caller runs it.
- ``cue_payload``: pure Python CUE-sheet bytes (authored body or default).
- ``regenerate_subtitle_sidecar_bytes`` / ``regenerate_nfo_sidecar_bytes`` /
  ``regenerate_cue_sidecar_bytes``: focused update_sidecar byte helpers.

The update_sidecar perturbed sub-seed is derived as
``sha256(f"{resolved_seed}/sidecar_update/{sidecar_id}/{event_id}")``
per spec design decision #7 (event_id ensures consecutive updates
produce distinct bytes).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from chaos_librarian.materializer.tooling.recipes import srt_payload

__all__ = [
    "cue_payload",
    "encode_subtitle_body",
    "perturbed_seed_for_update",
    "poster_ffmpeg_argv",
    "regenerate_cue_sidecar_bytes",
    "regenerate_nfo_sidecar_bytes",
    "regenerate_subtitle_sidecar_bytes",
    "render_nfo",
]


_SUBTITLE_PYTHON_ENCODING: Final[dict[str, str]] = {
    "utf8": "utf-8",
    "utf8_bom": "utf-8",
    "utf16_le": "utf-16-le",
    "iso_8859_1": "iso-8859-1",
}


def encode_subtitle_body(text: str, encoding: str | None) -> bytes:
    """Encode an SRT body. ``None`` ⇒ utf8; ``utf8_bom`` prepends a UTF-8 BOM.

    Raises:
        ValueError: ``encoding`` is not one of the supported subtitle encodings.
            The caller wraps this in a MediaActionError so the user sees
            E_MATERIALIZE_MEDIA_FAILED.
    """
    name = encoding or "utf8"
    python_codec = _SUBTITLE_PYTHON_ENCODING.get(name)
    if python_codec is None:
        raise ValueError(f"unsupported subtitle encoding {name!r}")
    body = text.encode(python_codec)
    if name == "utf8_bom":
        return b"\xef\xbb\xbf" + body
    return body


def cue_payload(*, body: str | None, sidecar_id: str) -> bytes:
    """Return CUE-sheet bytes: an authored ``body`` verbatim, else a default.

    The default is a minimal single-track CUE keyed on ``sidecar_id`` so two
    sidecars on the same run produce distinct, deterministic sheets.
    """
    if body is not None:
        return body.encode("utf-8")
    return (
        'PERFORMER "Chaos Librarian"\n'
        f'TITLE "{sidecar_id}"\n'
        f'FILE "{sidecar_id}.flac" WAVE\n'
        "  TRACK 01 AUDIO\n"
        '    TITLE "Track 1"\n'
        "    INDEX 01 00:00:00\n"
    ).encode()


def _seed_hash(*, stream: str, seed: int, keys: tuple[str, ...]) -> int:
    """Deterministic 64-bit int derived from (stream, seed, keys) via sha256.

    Mirrors the private ``_derive_subseed`` in ``determinism/rng.py`` but
    takes an arbitrary tuple of key components, so sidecar regeneration
    can incorporate both ``sidecar_id`` and ``event_id`` without
    spawning multiple sub-streams.
    """
    payload = f"{seed}/{stream}/" + "/".join(keys)
    digest = hashlib.sha256(payload.encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def render_nfo(*, sidecar_id: str) -> bytes:
    """Minimal Kodi-style NFO XML. Deterministic from sidecar_id."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<movie>\n"
        f"  <sidecar_id>{sidecar_id}</sidecar_id>\n"
        "  <generator>chaos-librarian</generator>\n"
        "</movie>\n"
    ).encode()


# Explicit ffmpeg image encoder per poster image_format (#118). ``png`` keeps
# the legacy implicit-extension behavior (no explicit ``-c:v``) so existing png
# poster bytes stay byte-identical; jpeg/webp name their encoders explicitly.
_POSTER_IMAGE_ENCODER: Final[dict[str, str]] = {
    "jpeg": "mjpeg",
    "webp": "libwebp",
}


def poster_ffmpeg_argv(
    *,
    output_path: Path,
    resolved_seed: int,
    sidecar_id: str,
    media_type: str | None = None,
    image_format: str | None = None,
) -> list[str]:
    """Build the ffmpeg argv for a poster sidecar.

    ``media_type`` ``None``/``"image"`` ⇒ a single-color still; ``"video"``
    ⇒ a tiny single-frame video muxed into the container the ``output_path``
    extension implies (the ``poster-is-video`` chaos). For an image poster,
    ``image_format`` (#118) selects the encoder explicitly (``jpeg``⇒mjpeg,
    ``webp``⇒libwebp); ``None``/``png`` keeps the legacy PNG (no explicit
    ``-c:v``). Hex color derived from (resolved_seed, sidecar_id) so different
    sidecars on the same run produce visually distinct output.
    """
    seed_hash = _seed_hash(stream="poster_color", seed=resolved_seed, keys=(sidecar_id,))
    color = f"{seed_hash & 0xFFFFFF:06x}"
    if media_type == "video":
        return [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=#{color}:s=320x240:d=0.04:r=25",
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
    encoder_flags: list[str] = []
    if image_format is not None and image_format in _POSTER_IMAGE_ENCODER:
        encoder_flags = ["-c:v", _POSTER_IMAGE_ENCODER[image_format]]
    return [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=#{color}:s=400x600:d=0.01:r=1",
        "-frames:v",
        "1",
        *encoder_flags,
        str(output_path),
    ]


def perturbed_seed_for_update(*, sidecar_id: str, event_id: str, resolved_seed: int) -> int:
    """Per spec design decision #7: distinct bytes for consecutive updates.

    Combines ``sidecar_id`` AND ``event_id`` so two updates on the same
    sidecar produce different bytes — the test surface (manifest
    ``content_hash``) can observe each update.
    """
    return _seed_hash(
        stream="sidecar_update",
        seed=resolved_seed,
        keys=(sidecar_id, event_id),
    )


def regenerate_subtitle_sidecar_bytes(
    *,
    language: str,
    sidecar_id: str,
    resolved_seed: int,
    event_id: str,
    duration_s: float,
    encoding: str | None = None,
) -> bytes:
    """Return regenerated SRT bytes for ``update_sidecar``.

    Uses the perturbed update seed so consecutive updates on the same sidecar
    produce distinct bytes, while preserving the sidecar's authored encoding.
    """
    perturbed_seed = perturbed_seed_for_update(
        sidecar_id=sidecar_id,
        event_id=event_id,
        resolved_seed=resolved_seed,
    )
    text = srt_payload(language=language, duration_s=duration_s, seed=perturbed_seed)
    return encode_subtitle_body(text, encoding)


def regenerate_nfo_sidecar_bytes(*, sidecar_id: str, body: str | None = None) -> bytes:
    """Return regenerated NFO bytes for ``update_sidecar``."""
    if body is not None:
        return body.encode("utf-8")
    return render_nfo(sidecar_id=sidecar_id)


def regenerate_cue_sidecar_bytes(*, sidecar_id: str, body: str | None = None) -> bytes:
    """Return regenerated CUE bytes for ``update_sidecar``."""
    return cue_payload(body=body, sidecar_id=sidecar_id)
