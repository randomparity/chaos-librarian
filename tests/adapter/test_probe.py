from __future__ import annotations

from chaos_librarian.adapter.probe import compare_probed_media
from chaos_librarian.contract.manifest import ProbedChapter, ProbedMedia, ProbedStream, StreamKind


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


def test_compare_probed_media_reports_chapter_and_attached_picture_mismatch() -> None:
    expected = _media(
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="png", attached_pic=True)],
    )
    expected.chapters.append(
        ProbedChapter(index=0, start_ms=0, end_ms=1000, title="Scene 01 abc123")
    )
    observed = _media(
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="png", attached_pic=False)],
    )

    differences = compare_probed_media(expected, observed)

    assert ("chapters.length", 1, 0) in differences
    assert ("streams.0.attached_pic", True, False) in differences


def test_compare_probed_media_reports_chapter_field_paths() -> None:
    expected = _media()
    expected.chapters.append(
        ProbedChapter(index=0, start_ms=0, end_ms=1000, title="Scene 01 abc123")
    )
    observed = _media()
    observed.chapters.append(
        ProbedChapter(index=0, start_ms=0, end_ms=1000, title="Scene 01 def456")
    )

    differences = compare_probed_media(expected, observed)

    assert ("chapters.0.title", "Scene 01 abc123", "Scene 01 def456") in differences


def test_compare_probed_media_reports_audio_layout_title_and_role_mismatch() -> None:
    expected = _media(
        streams=[
            ProbedStream(
                kind=StreamKind.AUDIO,
                codec="aac",
                channel_layout="3.0",
                title="Commentary",
                role="commentary",
            )
        ]
    )
    observed = _media(
        streams=[
            ProbedStream(
                kind=StreamKind.AUDIO,
                codec="aac",
                channel_layout="2.1",
                title="Main Audio",
                role="main",
            )
        ]
    )

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.channel_layout", "3.0", "2.1") in differences
    assert ("streams.0.title", "Commentary", "Main Audio") in differences
    assert ("streams.0.role", "commentary", "main") in differences


def test_compare_probed_media_treats_audio_video_unknown_language_as_equivalent() -> None:
    expected = _media(
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", language="und"),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", language=None),
        ]
    )
    observed = _media(
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", language=None),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="und"),
        ]
    )

    assert compare_probed_media(expected, observed) == []


def test_compare_probed_media_keeps_subtitle_language_strict() -> None:
    expected = _media(streams=[ProbedStream(kind=StreamKind.SUBTITLE, codec="srt", language="und")])
    observed = _media(streams=[ProbedStream(kind=StreamKind.SUBTITLE, codec="srt", language=None)])

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.language", "und", None) in differences


def test_compare_probed_media_reports_real_audio_video_language_mismatch() -> None:
    expected = _media(streams=[ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="eng")])
    observed = _media(streams=[ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="spa")])

    differences = compare_probed_media(expected, observed)

    assert ("streams.0.language", "eng", "spa") in differences
