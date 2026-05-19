"""Seed-driven content recipes — pure ffmpeg lavfi expressions.

Every recipe is a pure function over (dimensions, fps, duration, seed).
The orchestrator calls each recipe once per asset and hands the result
to ``ffmpeg.build_command``.

No subprocess work happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FFmpegInput:
    """One ffmpeg input + the extra flags that go with it.

    Exactly one of ``lavfi`` / ``file_path`` is set; the SRT-sidecar case
    uses ``file_path`` (read from a separately-written file).
    """

    lavfi: str | None = None
    file_path: Path | None = None
    extra_flags: tuple[str, ...] = ()


def _scale_from_seed(seed: int) -> float:
    """Deterministic 0.0-1.0 mapping for mandelbrot start_scale.

    The mapping is intentionally simple — bit-exactness requires only that
    the mapping be a pure function of ``seed``.
    """
    # uses 4 decimal places to keep the resulting lavfi string short and stable
    return round((abs(seed) % 1000) / 1000.0 + 1.5, 4)


def _hex_from_seed(seed: int) -> str:
    """Deterministic six-char hex color for solid_color."""
    return f"{abs(seed) % 0xFFFFFF:06x}"


def recipe_mandelbrot(
    *, width: int, height: int, fps: int, duration_s: float, seed: int
) -> FFmpegInput:
    """Mandelbrot zoom — visually rich, deterministic from seed."""
    start_scale = _scale_from_seed(seed)
    return FFmpegInput(
        lavfi=f"mandelbrot=size={width}x{height}:rate={fps}:start_scale={start_scale}",
        extra_flags=("-t", str(duration_s)),
    )


def recipe_color_bars(
    *, width: int, height: int, fps: int, duration_s: float, seed: int
) -> FFmpegInput:
    """SMPTE bars — visually distinctive, seed is ignored (deterministic)."""
    del seed  # bars are fully determined by dimensions + fps
    return FFmpegInput(
        lavfi=f"smptebars=size={width}x{height}:rate={fps}",
        extra_flags=("-t", str(duration_s)),
    )


def recipe_solid_color(
    *, width: int, height: int, fps: int, duration_s: float, seed: int
) -> FFmpegInput:
    """A single seeded color filling the frame."""
    hex_color = _hex_from_seed(seed)
    return FFmpegInput(
        lavfi=f"color=c=#{hex_color}:s={width}x{height}:r={fps}",
        extra_flags=("-t", str(duration_s)),
    )
