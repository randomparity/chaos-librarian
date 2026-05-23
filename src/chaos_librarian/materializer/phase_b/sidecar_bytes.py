"""Byte generators for non-subtitle sidecars + update_sidecar regeneration.

- ``render_nfo``: pure Python XML template. Returns bytes.
- ``poster_ffmpeg_argv``: returns the ffmpeg argv that will write a
  PNG via lavfi color source. The caller runs it.
- ``regenerate_sidecar``: dispatch by kind. Returns ``(bytes, None)``
  for subtitle/NFO; ``(None, argv)`` for poster.

The update_sidecar perturbed sub-seed is derived as
``sha256(f"{resolved_seed}/sidecar_update/{sidecar_id}/{event_id}")``
per spec design decision #7 (event_id ensures consecutive updates
produce distinct bytes).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.materializer.tooling.recipes import srt_payload

__all__ = [
    "perturbed_seed_for_update",
    "poster_ffmpeg_argv",
    "regenerate_sidecar",
    "render_nfo",
]


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


def poster_ffmpeg_argv(
    *,
    output_path: Path,
    resolved_seed: int,
    sidecar_id: str,
) -> list[str]:
    """Build the ffmpeg argv for a single-color PNG poster.

    Hex color derived from (resolved_seed, sidecar_id) so different
    sidecars on the same run produce visually distinct posters.
    """
    seed_hash = _seed_hash(stream="poster_color", seed=resolved_seed, keys=(sidecar_id,))
    color = f"{seed_hash & 0xFFFFFF:06x}"
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


def regenerate_sidecar(
    *,
    kind: SidecarKind,
    language: str | None,
    sidecar_id: str,
    resolved_seed: int,
    event_id: str,
    duration_s: float,
    output_path: Path | None = None,
) -> tuple[bytes | None, list[str] | None]:
    """Dispatch by kind. Returns ``(bytes, None)`` or ``(None, argv)``.

    ``output_path`` is required only for ``kind=POSTER`` (used in the
    ffmpeg argv).
    """
    perturbed_seed = perturbed_seed_for_update(
        sidecar_id=sidecar_id,
        event_id=event_id,
        resolved_seed=resolved_seed,
    )
    if kind == SidecarKind.SUBTITLE:
        if language is None:
            raise ValueError("subtitle sidecar requires language")
        body = srt_payload(language=language, duration_s=duration_s, seed=perturbed_seed).encode()
        return body, None
    if kind == SidecarKind.NFO:
        # NFO bytes don't depend on the seed (template is fixed); we
        # incorporate sidecar_id directly in the body.
        return render_nfo(sidecar_id=sidecar_id), None
    if kind == SidecarKind.POSTER:
        if output_path is None:
            raise ValueError("poster regeneration requires output_path")
        argv = poster_ffmpeg_argv(
            output_path=output_path,
            resolved_seed=perturbed_seed,
            sidecar_id=sidecar_id,
        )
        return None, argv
    raise ValueError(f"unknown sidecar kind {kind!r}")
