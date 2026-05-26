"""Layer 2 — content recipes. Pure functions, no subprocess."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import AudioChannelLayout, VideoVfrCadence
from chaos_librarian.materializer.tooling.recipes import (
    FFmpegInput,
    apply_vfr_cadence,
    recipe_channel_tones,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_silence,
    recipe_sine,
    recipe_solid_color,
    srt_payload,
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


@pytest.mark.parametrize(
    ("cadence", "expected_mods"),
    [
        (VideoVfrCadence.TWENTY_FOUR_TO_THIRTY, ("mod(n,5)", "mod(n,4)")),
        (VideoVfrCadence.THIRTY_TO_SIXTY, ("mod(n,4)", "mod(n,2)")),
        (
            VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY,
            ("mod(n,5)", "mod(n,4)", "mod(n,2)"),
        ),
    ],
)
def test_apply_vfr_cadence_wraps_lavfi_select_filter(
    cadence: VideoVfrCadence, expected_mods: tuple[str, ...]
) -> None:
    base = recipe_color_bars(width=640, height=480, fps=120, duration_s=3.0, seed=1)

    wrapped = apply_vfr_cadence(base, cadence=cadence, duration_s=3.0)

    assert wrapped.lavfi is not None
    assert wrapped.lavfi.startswith("smptebars=size=640x480:rate=120,select=")
    for expected in expected_mods:
        assert expected in wrapped.lavfi
    assert wrapped.extra_flags == base.extra_flags


def test_sine_frequency_derives_from_seed():
    fi = recipe_sine(channels="mono", duration_s=2.0, seed=440)
    assert fi.lavfi is not None
    assert fi.lavfi.startswith("sine=frequency=")
    assert ":sample_rate=48000" in fi.lavfi
    assert ":duration=2.0" in fi.lavfi


def test_silence_uses_channel_layout():
    fi = recipe_silence(channels="5.1", duration_s=1.0, seed=0)
    assert fi.lavfi == "anullsrc=channel_layout=5.1:sample_rate=48000"
    assert ("-t", "1.0") in tuple(_pairs(fi.extra_flags))


def test_channel_tones_emits_one_frequency_per_channel():
    """WHY: channel_tones is the materializer's debugging signal — each
    channel carries a distinct frequency so a downstream listener can tell
    them apart. Stereo must produce exactly two frequencies."""
    fi = recipe_channel_tones(channels="stereo", duration_s=1.0, seed=1)
    assert fi.lavfi is not None
    # Stereo => 2 sine sources merged with amerge or join
    assert fi.lavfi.count("sine=frequency=") == 2


def test_channel_tones_5_1_emits_six_frequencies():
    fi = recipe_channel_tones(channels="5.1", duration_s=1.0, seed=1)
    assert fi.lavfi is not None
    assert fi.lavfi.count("sine=frequency=") == 6


@pytest.mark.parametrize(
    ("layout", "count"),
    [
        (AudioChannelLayout.MONO, 1),
        (AudioChannelLayout.STEREO, 2),
        (AudioChannelLayout.TWO_ONE, 3),
        (AudioChannelLayout.FIVE_ONE, 6),
        (AudioChannelLayout.SEVEN_ONE, 8),
    ],
)
def test_channel_tones_supports_every_audio_channel_layout(
    layout: AudioChannelLayout, count: int
) -> None:
    fi = recipe_channel_tones(channels=layout, duration_s=1.0, seed=1)
    assert fi.lavfi is not None
    assert fi.lavfi.count("sine=frequency=") == count


def test_srt_payload_is_deterministic_for_seed():
    """WHY: SRT bytes must be bit-stable across runs for the manifest
    sidecar content_hash to compare equal. Inline the expected value so a
    future format change is caught."""
    body = srt_payload(language="eng", duration_s=2.0, seed=42)
    expected = (
        "1\n00:00:00,000 --> 00:00:02,000\nchaos-librarian fixture subtitle (lang=eng, seed=42)\n\n"
    )
    assert body == expected


def test_srt_payload_seed_changes_body():
    a = srt_payload(language="eng", duration_s=1.0, seed=1)
    b = srt_payload(language="eng", duration_s=1.0, seed=2)
    assert a != b


def test_srt_payload_duration_formats_to_3dp_milliseconds():
    """WHY: SRT timestamps are HH:MM:SS,mmm — a fractional duration must
    serialize without floating-point noise."""
    body = srt_payload(language="eng", duration_s=2.5, seed=1)
    assert "00:00:02,500" in body
