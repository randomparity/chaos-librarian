from __future__ import annotations

from chaos_librarian.adapter.probe import compare_probed_media
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind


def _media(
    *,
    duration: float = 60.0,
    streams: list[ProbedStream] | None = None,
) -> ProbedMedia:
    return ProbedMedia(
        container="matroska,webm",
        duration_seconds=duration,
        size_bytes=12345,
        streams=streams
        if streams is not None
        else [ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1920, height=1080)],
    )


def test_compare_probed_media_uses_point_zero_five_second_tolerance() -> None:
    tolerated = compare_probed_media(_media(duration=60.0), _media(duration=60.05))
    outside = compare_probed_media(_media(duration=60.0), _media(duration=60.051))

    assert tolerated == []
    assert ("duration_seconds", 60.0, 60.051) in outside


def test_compare_probed_media_reports_stream_field_paths() -> None:
    expected = _media(
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1920, height=1080),
            ProbedStream(
                kind=StreamKind.AUDIO,
                codec="aac",
                language="eng",
                channels=2,
                sample_rate=48_000,
            ),
        ]
    )
    observed = _media(
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="hevc", width=1280, height=720),
            ProbedStream(
                kind=StreamKind.AUDIO,
                codec="aac",
                language="fra",
                channels=2,
                sample_rate=44_100,
            ),
        ]
    )

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.codec", "h264", "hevc") in differences
    assert ("streams.0.width", 1920, 1280) in differences
    assert ("streams.1.language", "eng", "fra") in differences
    assert ("streams.1.sample_rate", 48_000, 44_100) in differences
