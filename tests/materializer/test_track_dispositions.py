"""Authored disposition intent must survive validation and media production."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import Asset, AudioTrack, SubtitleTrack
from chaos_librarian.materializer.content import synthesis as synthesis_mod
from chaos_librarian.materializer.content.synthesis import (
    _verify_dispositions,
    materialize_one_asset,
    write_sidecars,
)
from chaos_librarian.materializer.errors import (
    ProbeParseError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.preparation.preflight import preflight_asset
from chaos_librarian.materializer.tooling.ffmpeg import build_command
from chaos_librarian.materializer.tooling.recipes import FFmpegInput
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation
from tests.materializer.test_synthesis import _caps


def feature_asset(**updates: object) -> Asset:
    payload: dict[str, object] = {
        "id": "a_flags",
        "role": "main",
        "container": "mkv",
        "duration_seconds": 0.2,
        "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
        "audio": [
            {
                "codec": "aac",
                "channels": "stereo",
                "language": "eng",
                "default": True,
                "forced": False,
            }
        ]
        * 2,
        "subtitles": [
            {"codec": "srt", "language": "eng", "mode": "embedded", "default": True, "forced": True}
        ]
        * 2,
    }
    payload.update(updates)
    return Asset.model_validate(payload)


def test_flags_roundtrip_distinguishes_false_from_unspecified() -> None:
    asset = feature_asset()
    restored = Asset.model_validate_json(asset.model_dump_json())
    assert [(s.default, s.forced) for s in restored.subtitles] == [(True, True)] * 2
    assert restored.audio[0].forced is False
    assert (
        AudioTrack.model_validate({"codec": "aac", "channels": "stereo", "language": "eng"}).default
        is None
    )
    assert (
        SubtitleTrack.model_validate({"codec": "srt", "language": "eng", "mode": "sidecar"}).forced
        is None
    )


def test_typed_preflight_accepts_complete_feature() -> None:
    preflight_asset(parent_kind=ParentKind.MOVIE, asset=feature_asset())


@pytest.mark.parametrize(
    "updates",
    [
        {"duration_seconds": 31},
        {"duration_seconds": float("inf")},
        {"container": "mp4"},
        {"embedded_chapters": {"count": 2}},
        {"video": {"source": "color_bars", "codec": "h264", "resolution": "hd"}},
        {"matroska_muxing_profile": "no_cues"},
    ],
)
def test_typed_preflight_rejects_unsupported_asset_context(updates: dict[str, object]) -> None:
    with pytest.raises(UnsupportedMaterializationError):
        preflight_asset(parent_kind=ParentKind.MOVIE, asset=feature_asset(**updates))


def test_typed_preflight_rejects_partial_flags_and_ninth_track() -> None:
    asset = feature_asset()
    for audio in (asset.audio * 5, (asset.audio[0].model_copy(update={"forced": None}),)):
        with pytest.raises(UnsupportedMaterializationError):
            preflight_asset(
                parent_kind=ParentKind.MOVIE, asset=asset.model_copy(update={"audio": audio})
            )


def test_typed_preflight_accepts_maximum_tracks_and_duration() -> None:
    asset = feature_asset(duration_seconds=30)
    preflight_asset(
        parent_kind=ParentKind.MOVIE,
        asset=asset.model_copy(update={"audio": asset.audio * 4, "subtitles": asset.subtitles * 4}),
    )


def test_builder_maps_every_authored_stream_and_explicit_zero(tmp_path: Path) -> None:

    asset = feature_asset()
    audio = tuple(t.model_copy(update={"default": False}) for t in asset.audio)
    argv = build_command(
        video=asset.video,
        video_input=FFmpegInput(lavfi="color"),
        audios=audio,
        audio_inputs=[FFmpegInput(lavfi="sine")] * 2,
        subtitles=asset.subtitles,
        subtitle_inputs=[FFmpegInput(file_path=tmp_path / "s.srt")] * 2,
        duration_seconds=0.2,
        output_path=tmp_path / "out.mkv",
    )
    assert argv[argv.index("-disposition:a:0") + 1] == "0"
    assert argv[argv.index("-disposition:a:1") + 1] == "0"
    assert argv[argv.index("-disposition:s:1") + 1] == "default+forced"
    assert "-shortest" not in argv
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "-map"] == [
        "0:v:0",
        "1:a:0",
        "2:a:0",
        "3:s:0",
        "4:s:0",
    ]


def test_embedded_subtitles_do_not_create_sidecars(tmp_path: Path) -> None:

    result = write_sidecars(feature_asset(), tmp_path, 245, rendered_relative_path="flags.mkv")
    assert result == {}
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("updates", [{"default": None}, {"forced": False}])
def test_missing_or_changed_probe_flags_fail_intent_verification(
    updates: dict[str, object],
) -> None:
    asset = feature_asset()
    streams = [ProbedStream(kind=StreamKind.AUDIO, codec="aac", default=True, forced=False)] * 2
    streams += [
        ProbedStream(kind=StreamKind.SUBTITLE, codec="subrip", default=True, forced=True)
    ] * 2
    streams[-1] = streams[-1].model_copy(update=updates)
    media = ProbedMedia(
        container="matroska,webm", duration_seconds=0.2, size_bytes=100, streams=streams
    )
    with pytest.raises(ProbeParseError, match="requested"):
        _verify_dispositions(asset, media)
    media.streams.pop()
    with pytest.raises(ProbeParseError, match="expected 2 subtitle"):
        _verify_dispositions(asset, media)


def test_direct_synthesis_rejects_before_creating_output(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError):
        materialize_one_asset(
            feature_asset(duration_seconds=31),
            245,
            tmp_path / "run",
            _caps(),
            0,
            rendered_relative_path="flags.mkv",
        )
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("remux_container", {"container": "mp4"}),
        ("edit_metadata", {"fields": {"title": "Changed"}}),
        ("write_invalid_duration_metadata", {"value": "invalid"}),
    ],
)
def test_raw_validation_rejects_partial_flags_and_track_changing_timeline(
    action: str, fields: dict[str, object]
) -> None:
    asset = feature_asset().model_dump(mode="json")
    asset["audio"][0]["default"] = None
    payload = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "flags",
        "seed": 245,
        "duration_scale": "short",
        "library": {"roots": [{"id": "root", "path": "library"}]},
        "movies": [
            {
                "id": "movie",
                "title": "Flags",
                "layout": "movie_flat",
                "variants": [
                    {"id": "variant", "label": "sd", "bundle": {"id": "bundle", "assets": [asset]}}
                ],
            }
        ],
        "series": [],
        "artists": [],
        "timeline": [
            {
                "id": "edit",
                "at": "0ms",
                "action": action,
                "target": "a_flags",
                **fields,
            }
        ],
    }
    report = run_validation(
        prepare_run_input_from_bytes(raw_bytes=json.dumps(payload).encode(), source_label="flags")
    )
    assert not report.ok
    paths = [issue.path for issue in report.issues if issue.code == "E_MATERIALIZE_UNSUPPORTED"]
    assert any(path is not None and path.endswith(".audio[0].default") for path in paths)
    assert "$.timeline[0].action" in paths


@pytest.mark.parametrize("fail_tool", [False, True])
def test_private_subtitle_inputs_cleaned_after_tool_failure_or_size_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_tool: bool,
) -> None:
    inputs: list[Path] = []

    def fake_run(argv: list[str], **kwargs: object) -> tuple[ToolInvocation, str]:
        assert kwargs["max_output_bytes"] == 1024 * 1024
        inputs.extend(
            Path(argv[i + 1])
            for i, arg in enumerate(argv)
            if arg == "-i" and argv[i + 1].endswith(".srt")
        )
        assert len(inputs) == 2
        assert all(path.is_file() and path.name.startswith("subtitle-") for path in inputs)
        if not fail_tool:
            with Path(argv[-1]).open("wb") as output:
                output.truncate(64 * 1024 * 1024)
        return ToolInvocation(
            tool="ffmpeg", version="test", command=argv, exit_code=int(fail_tool), duration_ns=1
        ), "fixture failure"

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run)

    with pytest.raises(ToolFailedError if fail_tool else ProbeParseError):
        materialize_one_asset(
            feature_asset(), 245, tmp_path, _caps(), 0, rendered_relative_path="flags.mkv"
        )
    assert inputs
    assert all(not path.parent.exists() for path in inputs)
    assert not list((tmp_path / "library").glob("*.srt"))
