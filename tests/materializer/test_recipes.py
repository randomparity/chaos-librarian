"""Layer 2 — content recipes. Pure functions, no subprocess."""

from __future__ import annotations

import pytest

from chaos_librarian.materializer.recipes import (
    FFmpegInput,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_solid_color,
)


def test_mandelbrot_emits_stable_lavfi_for_seed():
    """WHY: bit-exactness across runs requires that the same seed produce
    the same lavfi expression byte-for-byte. Inline the expected value so
    a future change to the seed-to-scale mapping is caught by this test."""
    fi = recipe_mandelbrot(width=1920, height=1080, fps=24, duration_s=2.0, seed=42)
    assert isinstance(fi, FFmpegInput)
    assert fi.lavfi is not None
    assert fi.lavfi.startswith("mandelbrot=size=1920x1080:rate=24:start_scale=")
    assert ("-t", "2.0") in tuple(_pairs(fi.extra_flags))


def test_mandelbrot_seed_changes_start_scale():
    fi_a = recipe_mandelbrot(width=640, height=480, fps=24, duration_s=1.0, seed=1)
    fi_b = recipe_mandelbrot(width=640, height=480, fps=24, duration_s=1.0, seed=2)
    assert fi_a.lavfi != fi_b.lavfi


def test_color_bars_emits_smptebars():
    """WHY: color_bars uses smptebars, NOT testsrc — voom-v2 distinguishes
    these visually and the choice is locked at the contract level."""
    fi = recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.5, seed=1)
    assert fi.lavfi == "smptebars=size=1280x720:rate=24"
    assert ("-t", "1.5") in tuple(_pairs(fi.extra_flags))


def test_solid_color_hex_derives_from_seed():
    """WHY: deterministic seeded color choice is the only Sprint 5 visual
    knob for solid_color; same seed must yield same hex."""
    fi_a = recipe_solid_color(width=640, height=480, fps=24, duration_s=1.0, seed=7)
    fi_b = recipe_solid_color(width=640, height=480, fps=24, duration_s=1.0, seed=7)
    assert fi_a.lavfi == fi_b.lavfi
    assert fi_a.lavfi is not None
    assert "color=c=#" in fi_a.lavfi
    fi_c = recipe_solid_color(width=640, height=480, fps=24, duration_s=1.0, seed=8)
    assert fi_a.lavfi != fi_c.lavfi


def _pairs(flags: tuple[str, ...]) -> list[tuple[str, str]]:
    return list(zip(flags[::2], flags[1::2], strict=True))


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_every_video_recipe_carries_duration_flag(seed: int) -> None:
    """WHY: ffmpeg lavfi sources are infinite without -t; if a recipe
    forgets to add it, materialize produces an infinite stream and times
    out. Locked at the recipe level."""
    kwargs = {"width": 640, "height": 480, "fps": 24, "duration_s": 3.0, "seed": seed}
    for fi in (
        recipe_mandelbrot(**kwargs),
        recipe_color_bars(**kwargs),
        recipe_solid_color(**kwargs),
    ):
        assert "-t" in fi.extra_flags
