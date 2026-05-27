"""Pure subtitle sidecar recipe rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from chaos_librarian.contract.scenario import (
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    SubtitleTimingProfile,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.recipes import _srt_timestamp

_SRT_ENCODINGS: Final[frozenset[SubtitleEncoding]] = frozenset(
    {
        SubtitleEncoding.UTF8,
        SubtitleEncoding.UTF8_BOM,
        SubtitleEncoding.UTF16_LE,
        SubtitleEncoding.ISO_8859_1,
    }
)
_ASS_ENCODINGS: Final[frozenset[SubtitleEncoding]] = frozenset(
    {SubtitleEncoding.UTF8, SubtitleEncoding.UTF8_BOM}
)
_RECIPE_MATRIX: Final[dict[tuple[SubtitleCodec, SubtitleSource], frozenset[SubtitleEncoding]]] = {
    (SubtitleCodec.SRT, SubtitleSource.GENERATED_SRT): _SRT_ENCODINGS,
    (SubtitleCodec.ASS, SubtitleSource.STYLED_ASS): _ASS_ENCODINGS,
    (SubtitleCodec.SSA, SubtitleSource.STYLED_ASS): _ASS_ENCODINGS,
}


@dataclass(frozen=True, slots=True)
class _Cue:
    start_s: float
    end_s: float
    text: str


def subtitle_payload_bytes(
    *,
    codec: SubtitleCodec,
    source: SubtitleSource,
    encoding: SubtitleEncoding,
    timing_profile: SubtitleTimingProfile,
    language: str,
    duration_s: float,
    seed: int,
) -> bytes:
    """Render deterministic subtitle sidecar bytes for one declared track."""
    _validate_recipe(codec=codec, source=source, encoding=encoding)
    cues = _cues(
        timing_profile=timing_profile,
        language=language,
        duration_s=duration_s,
        seed=seed,
    )
    text = _srt_text(cues) if codec is SubtitleCodec.SRT else _ass_text(cues, codec=codec)
    return _encode_text(text, encoding=encoding)


def _validate_recipe(
    *,
    codec: SubtitleCodec,
    source: SubtitleSource,
    encoding: SubtitleEncoding,
) -> None:
    supported_encodings = _RECIPE_MATRIX.get((codec, source))
    if supported_encodings is None:
        raise UnsupportedMaterializationError(
            "unsupported subtitle codec/source recipe combination",
            field="subtitle.source",
            payload={"codec": codec.value, "source": source.value},
        )
    if encoding not in supported_encodings:
        raise UnsupportedMaterializationError(
            "unsupported subtitle encoding for codec/source recipe",
            field="subtitle.encoding",
            payload={"codec": codec.value, "encoding": encoding.value},
        )


def _cues(
    *,
    timing_profile: SubtitleTimingProfile,
    language: str,
    duration_s: float,
    seed: int,
) -> tuple[_Cue, ...]:
    safe_duration = max(duration_s, 0.001)
    base_text = f"chaos-librarian fixture subtitle (lang={language}, seed={seed})"
    if timing_profile is SubtitleTimingProfile.NORMAL:
        return (_Cue(start_s=0.0, end_s=safe_duration, text=base_text),)
    if timing_profile is SubtitleTimingProfile.OVERLAP:
        first_end = min(safe_duration, 1.0)
        second_start = max(0.0, first_end / 2.0)
        return (
            _Cue(start_s=0.0, end_s=first_end, text=f"{base_text} overlap-a"),
            _Cue(start_s=second_start, end_s=safe_duration, text=f"{base_text} overlap-b"),
        )
    if timing_profile is SubtitleTimingProfile.OUT_OF_RANGE:
        return (_Cue(start_s=0.0, end_s=safe_duration + 30.0, text=f"{base_text} out-of-range"),)
    raise UnsupportedMaterializationError(
        "unsupported subtitle timing profile",
        field="subtitle.timing_profile",
        payload={"timing_profile": timing_profile.value},
    )


def _srt_text(cues: tuple[_Cue, ...]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            "\n".join(
                (
                    str(index),
                    f"{_srt_timestamp(cue.start_s)} --> {_srt_timestamp(cue.end_s)}",
                    cue.text,
                    "",
                )
            )
        )
    return "\n".join(blocks) + "\n"


def _ass_text(cues: tuple[_Cue, ...], *, codec: SubtitleCodec) -> str:
    style_section, style_format, style_line, event_format = _ass_style_lines(codec)
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+" if codec is SubtitleCodec.ASS else "ScriptType: v4.00",
        "PlayResX: 640",
        "PlayResY: 480",
        "",
        style_section,
        style_format,
        style_line,
        "",
        "[Events]",
        event_format,
    ]
    for index, cue in enumerate(cues):
        x = 320 + (index * 12)
        y = 420 - (index * 20)
        text = rf"{{\pos({x},{y})}}{cue.text}"
        lines.append(_ass_dialogue_line(cue=cue, codec=codec, text=text))
    return "\n".join(lines) + "\n"


def _ass_style_lines(codec: SubtitleCodec) -> tuple[str, str, str, str]:
    if codec is SubtitleCodec.ASS:
        return (
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
            "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding",
            "Style: ChaosDefault,Arial,28,&H00FFFFFF,&H000000FF,&H00000000,"
            "&H64000000,0,0,0,0,100,100,0,0,1,1,0,2,20,20,30,1",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        )
    return (
        "[V4 Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "TertiaryColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, AlphaLevel, Encoding",
        "Style: ChaosDefault,Arial,28,16777215,65535,255,0,0,0,1,1,0,2,20,20,30,0,1",
        "Format: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    )


def _ass_dialogue_line(*, cue: _Cue, codec: SubtitleCodec, text: str) -> str:
    start = _ass_timestamp(cue.start_s)
    end = _ass_timestamp(cue.end_s)
    if codec is SubtitleCodec.ASS:
        return f"Dialogue: 0,{start},{end},ChaosDefault,,0000,0000,0000,,{text}"
    return f"Dialogue: Marked=0,{start},{end},ChaosDefault,,0000,0000,0000,,{text}"


def _ass_timestamp(seconds: float) -> str:
    total_centiseconds = max(0, round(seconds * 100))
    centiseconds = total_centiseconds % 100
    total_seconds = total_centiseconds // 100
    seconds_part = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours}:{minutes:02d}:{seconds_part:02d}.{centiseconds:02d}"


def _encode_text(text: str, *, encoding: SubtitleEncoding) -> bytes:
    if encoding is SubtitleEncoding.UTF8:
        return text.encode("utf-8")
    if encoding is SubtitleEncoding.UTF8_BOM:
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    if encoding is SubtitleEncoding.UTF16_LE:
        return b"\xff\xfe" + text.encode("utf-16-le")
    if encoding is SubtitleEncoding.ISO_8859_1:
        return text.encode("iso-8859-1")
    raise UnsupportedMaterializationError(
        "unsupported subtitle encoding",
        field="subtitle.encoding",
        payload={"encoding": encoding.value},
    )
