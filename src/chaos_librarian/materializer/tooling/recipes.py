"""Seed-driven content recipes — pure ffmpeg lavfi expressions.

Every recipe is a pure function over (dimensions, fps, duration, seed).
The orchestrator calls each recipe once per asset and hands the result
to ``ffmpeg.build_command``.

No subprocess work happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from chaos_librarian.contract.scenario import (
    AUDIO_CHANNEL_COUNTS_BY_NAME,
    AUDIO_CHANNEL_ORDER_BY_NAME,
    AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME,
    AudioNoiseColor,
    AudioSampleFormat,
    VideoFieldOrder,
    VideoVfrCadence,
)


@dataclass(frozen=True, slots=True)
class FFmpegInput:
    """One ffmpeg input + the extra flags that go with it.

    Exactly one of ``lavfi`` / ``file_path`` is set; the SRT-sidecar case
    uses ``file_path`` (read from a separately-written file).
    """

    lavfi: str | None = None
    file_path: Path | None = None
    extra_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (self.lavfi is None) == (self.file_path is None):
            raise ValueError("FFmpegInput requires exactly one of lavfi or file_path")


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


VFR_BASE_FPS: Final = 120
_CADENCE_SELECT_MODS: Final[dict[VideoVfrCadence, tuple[int, ...]]] = {
    VideoVfrCadence.TWENTY_FOUR_TO_THIRTY: (5, 4),
    VideoVfrCadence.THIRTY_TO_SIXTY: (4, 2),
    VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY: (5, 4, 2),
}
_FIELD_ORDER_FILTERS: Final[dict[VideoFieldOrder, str]] = {
    VideoFieldOrder.TOP_FIELD_FIRST: "tinterlace=mode=interleave_top,setfield=tff",
    VideoFieldOrder.BOTTOM_FIELD_FIRST: "tinterlace=mode=interleave_bottom,setfield=bff",
}


def apply_vfr_cadence(
    ffmpeg_input: FFmpegInput, *, cadence: VideoVfrCadence, duration_s: float
) -> FFmpegInput:
    """Wrap a lavfi video input with a deterministic VFR frame-selection filter."""
    if ffmpeg_input.lavfi is None:
        raise ValueError("VFR cadence requires a lavfi video input")
    filters = _vfr_select_filter(cadence=cadence, duration_s=duration_s)
    return FFmpegInput(
        lavfi=f"{ffmpeg_input.lavfi},{filters}",
        extra_flags=ffmpeg_input.extra_flags,
    )


def apply_interlaced_field_order(
    ffmpeg_input: FFmpegInput, *, field_order: VideoFieldOrder
) -> FFmpegInput:
    """Wrap a lavfi video input with deterministic interlaced field ordering."""
    if ffmpeg_input.lavfi is None:
        raise ValueError("interlaced field order requires a lavfi video input")
    return FFmpegInput(
        lavfi=f"{ffmpeg_input.lavfi},{_FIELD_ORDER_FILTERS[field_order]}",
        extra_flags=ffmpeg_input.extra_flags,
    )


def _vfr_select_filter(*, cadence: VideoVfrCadence, duration_s: float) -> str:
    mods = _CADENCE_SELECT_MODS[cadence]
    segment_s = duration_s / len(mods)
    expression = _select_expression(mods=mods, segment_s=segment_s)
    return f"select='{expression}'"


def _select_expression(*, mods: tuple[int, ...], segment_s: float) -> str:
    expression = f"not(mod(n,{mods[-1]}))"
    for index in range(len(mods) - 2, -1, -1):
        boundary = round(segment_s * (index + 1), 6)
        expression = f"if(lt(t,{boundary}),not(mod(n,{mods[index]})),{expression})"
    return expression


_CHANNEL_COUNTS = AUDIO_CHANNEL_COUNTS_BY_NAME
# Distinct base frequencies; all stay below the 48 kHz sample rate's Nyquist limit.
_CHANNEL_TONE_BASE = (220, 440, 880, 1760, 3520, 7040, 10560, 14080)
_FFMPEG_SAMPLE_FORMATS: Final[dict[AudioSampleFormat, str]] = {
    AudioSampleFormat.S16: "s16",
    AudioSampleFormat.S24: "s32",
    AudioSampleFormat.FLT: "flt",
}


def _frequency_from_seed(seed: int) -> int:
    """Map seed to a sine frequency in the 100-1000 Hz human-audible band."""
    return 100 + (abs(seed) % 901)


def _ffmpeg_layout(channels: str) -> str:
    return AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME[channels]


def _channel_order(channels: str) -> tuple[str, ...]:
    return AUDIO_CHANNEL_ORDER_BY_NAME[channels]


def _pan_mono_to_layout(lavfi: str, channels: str) -> str:
    order = _channel_order(channels)
    if len(order) == 1:
        return lavfi
    mappings = "|".join(f"{channel}=c0" for channel in order)
    return f"{lavfi},pan={_ffmpeg_layout(channels)}|{mappings}"


def _join_channel_tone_sources(sources: list[str], channels: str) -> str:
    order = _channel_order(channels)
    labeled = [f"{source}[a{index}]" for index, source in enumerate(sources)]
    merge_inputs = "".join(f"[a{index}]" for index in range(len(sources)))
    maps = "|".join(f"{index}.0-{channel}" for index, channel in enumerate(order))
    join = (
        f"{merge_inputs}join=inputs={len(sources)}:"
        f"channel_layout={_ffmpeg_layout(channels)}:map={maps}"
    )
    return ";".join([*labeled, join])


def recipe_sine(
    *,
    channels: str,
    duration_s: float,
    seed: int,
    noise_color: AudioNoiseColor | None = None,
    sample_rate: int = 48000,
    sample_format: AudioSampleFormat | None = None,
) -> FFmpegInput:
    """A single sine tone — frequency derived from seed; channel layout
    set via the lavfi source so the muxer sees the requested layout."""
    del noise_color
    freq = _frequency_from_seed(seed)
    lavfi = _pan_mono_to_layout(
        f"sine=frequency={freq}:duration={duration_s}:sample_rate={sample_rate}",
        channels,
    )
    return FFmpegInput(
        lavfi=_apply_audio_sample_format(lavfi, sample_format),
        extra_flags=(),
    )


def recipe_silence(
    *,
    channels: str,
    duration_s: float,
    seed: int,
    noise_color: AudioNoiseColor | None = None,
    sample_rate: int = 48000,
    sample_format: AudioSampleFormat | None = None,
) -> FFmpegInput:
    """anullsrc — zero-amplitude audio at the requested channel layout."""
    del seed, noise_color  # silence is fully determined by channels + duration/rate
    return FFmpegInput(
        lavfi=_apply_audio_sample_format(
            f"anullsrc=channel_layout={_ffmpeg_layout(channels)}:sample_rate={sample_rate}",
            sample_format,
        ),
        extra_flags=("-t", str(duration_s)),
    )


def recipe_channel_tones(
    *,
    channels: str,
    duration_s: float,
    seed: int,
    noise_color: AudioNoiseColor | None = None,
    sample_rate: int = 48000,
    sample_format: AudioSampleFormat | None = None,
) -> FFmpegInput:
    """One distinct sine frequency per channel — debugging signal.

    Frequencies start from the seed-derived base and double per channel.
    Multi-channel layouts build a filtergraph with one sine source per
    channel linked into FFmpeg's ``join`` filter with an explicit layout.
    """
    del noise_color
    count = _CHANNEL_COUNTS[channels]
    base_index = abs(seed) % len(_CHANNEL_TONE_BASE)
    sources: list[str] = []
    for offset in range(count):
        freq = _CHANNEL_TONE_BASE[(base_index + offset) % len(_CHANNEL_TONE_BASE)]
        sources.append(f"sine=frequency={freq}:duration={duration_s}:sample_rate={sample_rate}")
    lavfi = sources[0] if count == 1 else _join_channel_tone_sources(sources, channels)
    return FFmpegInput(lavfi=_apply_audio_sample_format(lavfi, sample_format), extra_flags=())


def recipe_noise(
    *,
    channels: str,
    duration_s: float,
    seed: int,
    noise_color: AudioNoiseColor | None = None,
    sample_rate: int = 48000,
    sample_format: AudioSampleFormat | None = None,
) -> FFmpegInput:
    """Seeded anoisesrc using the requested noise color."""
    color = AudioNoiseColor.WHITE if noise_color is None else noise_color
    lavfi = (
        f"anoisesrc=color={color.value}:duration={duration_s}:"
        f"sample_rate={sample_rate}:seed={abs(seed)}"
    )
    lavfi = _pan_mono_to_layout(lavfi, channels)
    return FFmpegInput(lavfi=_apply_audio_sample_format(lavfi, sample_format), extra_flags=())


def _apply_audio_sample_format(
    lavfi: str,
    sample_format: AudioSampleFormat | None,
) -> str:
    if sample_format is None:
        return lavfi
    return f"{lavfi},aformat=sample_fmts={_FFMPEG_SAMPLE_FORMATS[sample_format]}"


def _srt_timestamp(seconds: float) -> str:
    """Format ``HH:MM:SS,mmm`` from a float of seconds."""
    total_ms = round(seconds * 1000)
    hh, rem = divmod(total_ms, 3_600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def srt_payload(*, language: str, duration_s: float, seed: int) -> str:
    """Return SRT body for one subtitle cue spanning [0, duration_s).

    Single-cue, single-line body that includes the seed so adapters can
    distinguish fixtures at a glance. Trailing blank line required by SRT.
    """
    return (
        "1\n"
        f"00:00:00,000 --> {_srt_timestamp(duration_s)}\n"
        f"chaos-librarian fixture subtitle (lang={language}, seed={seed})\n"
        "\n"
    )
