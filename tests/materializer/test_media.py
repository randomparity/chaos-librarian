"""Tests for materializer/media.py."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import (
    Asset,
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    PosterImageFormat,
    SidecarMediaType,
    TimelineActionName,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.phase_b.media import handler as media_module
from chaos_librarian.materializer.phase_b.media.handler import (
    LivePosterSidecar,
    LiveSubtitleSidecar,
    MediaPhaseBContext,
    _subtitle_codec_for_container,
    apply_media_action,
)
from chaos_librarian.materializer.tooling._subprocess import RecordedToolResult
from chaos_librarian.materializer.tooling.recipes import srt_payload


def test_subtitle_codec_mkv_uses_srt():
    assert _subtitle_codec_for_container("mkv") == "srt"


def test_subtitle_codec_webm_uses_srt():
    assert _subtitle_codec_for_container("webm") == "srt"


def test_subtitle_codec_mp4_uses_mov_text():
    assert _subtitle_codec_for_container("mp4") == "mov_text"


def test_subtitle_codec_m4v_uses_mov_text():
    assert _subtitle_codec_for_container("m4v") == "mov_text"


def test_subtitle_codec_mov_uses_mov_text():
    assert _subtitle_codec_for_container("mov") == "mov_text"


def test_subtitle_codec_unsupported_container_raises():
    with pytest.raises(ValueError, match="unsupported"):
        _subtitle_codec_for_container("ogg")


def test_media_context_construction(tmp_path):
    ctx = MediaPhaseBContext(
        library_root=tmp_path,
        scenario_assets={},
        resolved_seed=42,
        ffmpeg_version="7.0",
        ffprobe_version="7.0",
        post_phase_b_versions={},
        post_phase_b_sidecars={},
        invocations=[],
    )
    assert ctx.library_root == tmp_path
    assert ctx.resolved_seed == 42
    assert ctx.post_phase_b_versions == {}


def _atomic_entry(
    *,
    event_id,
    action,
    target,
    state_delta,
    input_version_ids=None,
    output_version_ids=None,
):
    return AtomicJournalEntry(
        schema_version=1,
        event_id=event_id,
        scenario_id="sc",
        run_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        logical_time_ns=0,
        action=action.value,
        target_ids=[target],
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        location_ids=[],
        state_delta=state_delta,
        phase=JournalPhase.ATOMIC,
    )


@pytest.fixture
def media_ctx(tmp_path):
    return MediaPhaseBContext(
        library_root=tmp_path,
        scenario_assets={
            "a0": Asset(
                id="a0",
                role="main",
                container="mkv",
                duration_seconds=1.0,
                video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
                audio=(
                    AudioTrack(
                        source=AudioSource.SINE,
                        codec="aac",
                        channels=AudioChannelLayout.STEREO,
                        language="eng",
                    ),
                ),
            )
        },
        resolved_seed=42,
        ffmpeg_version="7.0",
        ffprobe_version="7.0",
    )


def _stub_ffmpeg_writes(monkeypatch, *, stub_bytes=b"x" * 100, exit_code=0):
    """Mock run_ffmpeg + probe_file: write stub bytes; return canned ProbedMedia."""

    def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
        # The output path is the LAST positional argv element.
        Path(argv[-1]).write_bytes(stub_bytes)
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=list(argv),
            exit_code=exit_code,
            duration_ns=1000,
        )
        return invocation, ""

    def fake_probe(path, **_kwargs):
        return ProbedMedia(
            container="matroska",
            duration_seconds=1.0,
            size_bytes=len(stub_bytes),
            streams=[],
        )

    monkeypatch.setattr("chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run)
    monkeypatch.setattr("chaos_librarian.materializer.phase_b.media.handler.probe_file", fake_probe)


def test_version_media_action_assembles_common_version_fields(monkeypatch):
    helper = getattr(media_module, "_version_media_action", None)
    assert helper is not None, "version-producing media handlers should share action assembly"
    monkeypatch.setattr(media_module.time, "monotonic_ns", lambda: 2_500)
    entry = _atomic_entry(
        event_id="ev_version",
        action=TimelineActionName.REENCODE_VIDEO,
        target="a0",
        input_version_ids=["v0"],
        output_version_ids=["v1"],
        state_delta={
            "resolution": "sd",
            "codec": "h264",
            "input_path": "x.mkv",
            "output_path": "x.mkv",
        },
    )
    version = media_module._VersionOutput(
        version_id="v1",
        content_hash="sha256:" + "a" * 64,
    )

    result = helper(
        entry=entry,
        action=TimelineActionName.REENCODE_VIDEO,
        version=version,
        tool_invocation_index=7,
        started_ns=2_000,
    )

    assert result.event_id == "ev_version"
    assert result.action == TimelineActionName.REENCODE_VIDEO
    assert result.target_asset_id == "a0"
    assert result.input_path == "x.mkv"
    assert result.output_path == "x.mkv"
    assert result.input_version_id == "v0"
    assert result.output_version_id == "v1"
    assert result.output_content_hash == "sha256:" + "a" * 64
    assert result.tool_invocation_index == 7
    assert result.duration_ns == 500


class TestApplyReencodeVideo:
    def test_apply_reencode_video_writes_output_and_returns_media_action(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"x" * 100)
        entry = _atomic_entry(
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "resolution": "sd",
                "codec": "h264",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.mkv").read_bytes() == b"x" * 100
        expected_hash = "sha256:" + hashlib.sha256(b"x" * 100).hexdigest()
        assert result.output_content_hash == expected_hash
        assert result.action == TimelineActionName.REENCODE_VIDEO
        assert result.output_version_id == "v1"
        assert media_ctx.post_phase_b_versions["v1"][0] == expected_hash

    def test_apply_reencode_video_uses_temp_sibling_for_atomic_write(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured_argv: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv.append(list(argv))
            Path(argv[-1]).write_bytes(b"x" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1000,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="matroska", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "resolution": "sd",
                "codec": "h264",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        # The ffmpeg argv's output path should be a temp sibling like
        # x.mkv.tmp.42 (resolved_seed=42 from the fixture).
        output_arg = captured_argv[0][-1]
        assert ".tmp." in output_arg

    def test_apply_reencode_video_nonzero_exit_wraps_in_media_action_error(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, exit_code=1)
        entry = _atomic_entry(
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "resolution": "sd",
                "codec": "h264",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)
        assert exc_info.value.event_id == "ev_rv_001"
        assert exc_info.value.action == TimelineActionName.REENCODE_VIDEO

    def test_apply_reencode_video_unknown_resolution_raises(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        # ffmpeg must NOT be invoked: an unknown resolution is rejected before
        # encoding rather than silently falling back to SD.
        ffmpeg_calls: list[int] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            ffmpeg_calls.append(1)
            raise AssertionError("ffmpeg invoked for unknown resolution")

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        entry = _atomic_entry(
            event_id="ev_rv_bad",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "resolution": "4k",
                "codec": "h264",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)
        assert exc_info.value.action == TimelineActionName.REENCODE_VIDEO
        assert "4k" in str(exc_info.value)
        assert ffmpeg_calls == []


class TestApplyReencodeAudio:
    def test_apply_reencode_audio_writes_output(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"x" * 100)
        entry = _atomic_entry(
            event_id="ev_ra_001",
            action=TimelineActionName.REENCODE_AUDIO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_channels": "5.1",
                "to_channels": "stereo",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.mkv").read_bytes() == b"x" * 100
        expected_hash = "sha256:" + hashlib.sha256(b"x" * 100).hexdigest()
        assert result.output_content_hash == expected_hash
        assert result.action == TimelineActionName.REENCODE_AUDIO
        assert result.output_version_id == "v1"
        assert media_ctx.post_phase_b_versions["v1"][0] == expected_hash

    def test_apply_reencode_audio_argv_uses_ac_to_channels(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured_argv: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv.append(list(argv))
            Path(argv[-1]).write_bytes(b"x" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1000,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="matroska", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_ra_001",
            action=TimelineActionName.REENCODE_AUDIO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_channels": "5.1",
                "to_channels": "stereo",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured_argv[0]
        assert "-ac" in argv
        # Channel-name strings are translated to integer counts before
        # ffmpeg sees -ac (#58: ffmpeg rejects "stereo").
        assert argv[argv.index("-ac") + 1] == "2"

    def test_apply_reencode_audio_argv_maps_5_1_to_6(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured_argv: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv.append(list(argv))
            Path(argv[-1]).write_bytes(b"x" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1000,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="matroska", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_ra_002",
            action=TimelineActionName.REENCODE_AUDIO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_channels": "stereo",
                "to_channels": "5.1",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured_argv[0]
        assert argv[argv.index("-ac") + 1] == "6"

    def test_apply_reencode_audio_uses_track_asset_codec(self, monkeypatch, tmp_path):
        (tmp_path / "x.flac").write_bytes(b"y" * 50)
        captured_argv: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv.append(list(argv))
            Path(argv[-1]).write_bytes(b"x" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1000,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="flac", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        media_ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={
                "asset_track": Asset(
                    id="asset_track",
                    role="primary_audio",
                    container="flac",
                    duration_seconds=1.0,
                    audio=(
                        AudioTrack(
                            source=AudioSource.SINE,
                            codec="flac",
                            channels=AudioChannelLayout.STEREO,
                            language="eng",
                        ),
                    ),
                )
            },
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        entry = _atomic_entry(
            event_id="ev_ra_track",
            action=TimelineActionName.REENCODE_AUDIO,
            target="asset_track",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_channels": "stereo",
                "to_channels": "mono",
                "input_path": "x.flac",
                "output_path": "x.flac",
            },
        )

        apply_media_action(media_ctx, entry)

        argv = captured_argv[0]
        assert argv[argv.index("-c:a") + 1] == "flac"

    def test_apply_reencode_audio_unknown_channel_layout_raises(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        # ffmpeg must NOT be invoked: assert by failing the fake.
        ffmpeg_calls: list[int] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            ffmpeg_calls.append(1)
            raise AssertionError("ffmpeg invoked for unknown channel layout")

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        entry = _atomic_entry(
            event_id="ev_ra_bad",
            action=TimelineActionName.REENCODE_AUDIO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_channels": "stereo",
                "to_channels": "foo",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)
        assert exc_info.value.action == TimelineActionName.REENCODE_AUDIO
        assert "foo" in str(exc_info.value)
        assert ffmpeg_calls == []


class TestApplyRemuxContainer:
    def test_apply_remux_writes_to_new_extension(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"r" * 100)
        entry = _atomic_entry(
            event_id="ev_rmx_001",
            action=TimelineActionName.REMUX_CONTAINER,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_container": "mkv",
                "to_container": "mp4",
                "from_path": "x.mkv",
                "to_path": "x.mp4",
                "input_path": "x.mkv",
                "output_path": "x.mp4",
            },
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.mp4").exists()
        assert result.output_path == "x.mp4"

    def test_apply_remux_argv_uses_c_copy(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"r" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1000,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="mp4", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_rmx_001",
            action=TimelineActionName.REMUX_CONTAINER,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_container": "mkv",
                "to_container": "mp4",
                "from_path": "x.mkv",
                "to_path": "x.mp4",
                "input_path": "x.mkv",
                "output_path": "x.mp4",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        assert "-c" in argv
        assert argv[argv.index("-c") + 1] == "copy"

    def test_apply_remux_unlinks_old_extension_input(self, media_ctx, monkeypatch, tmp_path):
        """Issue #60: after a successful remux the old-extension input must be unlinked.

        Otherwise the manifest only references the new file but the
        old-extension file persists as dead bytes in the library.
        """
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"r" * 100)
        entry = _atomic_entry(
            event_id="ev_rmx_unlink",
            action=TimelineActionName.REMUX_CONTAINER,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_container": "mkv",
                "to_container": "mp4",
                "from_path": "x.mkv",
                "to_path": "x.mp4",
                "input_path": "x.mkv",
                "output_path": "x.mp4",
            },
        )
        apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.mp4").exists()
        assert not (tmp_path / "x.mkv").exists()

    def test_apply_remux_no_unlink_when_input_equals_output(self, media_ctx, monkeypatch, tmp_path):
        """Invariant: when input_path == output_path (same resolved path),
        the post-rename unlink is a no-op — the temp-rename has already
        overwritten the file at that location. The engine never emits
        remux events with matching paths today, but the guard documents
        the invariant and protects against accidental data loss.
        """
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"r" * 100)
        entry = _atomic_entry(
            event_id="ev_rmx_noop",
            action=TimelineActionName.REMUX_CONTAINER,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "from_container": "mkv",
                "to_container": "mkv",
                "from_path": "x.mkv",
                "to_path": "x.mkv",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        # The file at the shared path still exists with the new bytes;
        # no unlink fired (otherwise the file would be gone).
        assert (tmp_path / "x.mkv").exists()
        assert (tmp_path / "x.mkv").read_bytes() == b"r" * 100


class TestApplyEditMetadata:
    def test_apply_edit_metadata_argv_passes_each_field(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"m" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1000,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="matroska", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_em_001",
            action=TimelineActionName.EDIT_METADATA,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "fields": {"title": "Pulsar", "year": "2026"},
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        # Each field must appear as -metadata key=value
        assert "title=Pulsar" in argv
        assert "year=2026" in argv


class TestApplyEmbedSubtitle:
    def test_apply_embed_unlinks_sidecar_after_success(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        (tmp_path / "x.eng.srt").write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nhi\n\n")
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"e" * 100)
        entry = _atomic_entry(
            event_id="ev_es_001",
            action=TimelineActionName.EMBED_SUBTITLE,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "embedded_sidecar_id": "sidecar_0001",
                "embedded_sidecar_path": "x.eng.srt",
                "language": "eng",
                "kind": "subtitle",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        # Sidecar file consumed.
        assert not (tmp_path / "x.eng.srt").exists()

    def test_apply_embed_mkv_uses_srt_codec(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        (tmp_path / "x.eng.srt").write_bytes(b"1\n")
        captured: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"e" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="matroska", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_es_001",
            action=TimelineActionName.EMBED_SUBTITLE,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "embedded_sidecar_id": "sidecar_0001",
                "embedded_sidecar_path": "x.eng.srt",
                "language": "eng",
                "kind": "subtitle",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        # mkv output → -c:s srt
        assert "-c:s" in argv
        assert argv[argv.index("-c:s") + 1] == "srt"

    def test_apply_embed_mp4_uses_mov_text_codec(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mp4").write_bytes(b"y" * 50)
        (tmp_path / "x.eng.srt").write_bytes(b"1\n")
        captured: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"e" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.probe_file",
            lambda p, **k: ProbedMedia(
                container="mp4", duration_seconds=1.0, size_bytes=100, streams=[]
            ),
        )
        entry = _atomic_entry(
            event_id="ev_es_001",
            action=TimelineActionName.EMBED_SUBTITLE,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "embedded_sidecar_id": "sidecar_0001",
                "embedded_sidecar_path": "x.eng.srt",
                "language": "eng",
                "kind": "subtitle",
                "input_path": "x.mp4",
                "output_path": "x.mp4",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        assert argv[argv.index("-c:s") + 1] == "mov_text"


class TestApplyExtractSubtitle:
    def test_apply_extract_writes_srt_at_to_path(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"s" * 100)
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler._probe_subtitle_index_for_language",
            lambda ctx, path, lang: 0,
        )
        entry = _atomic_entry(
            event_id="ev_xs_001",
            action=TimelineActionName.EXTRACT_SUBTITLE,
            target="a0",
            state_delta={
                "sidecar_id": "sidecar_0002",
                "sidecar_path": "x.fra.srt",
                "language": "fra",
                "input_path": "x.mkv",
            },
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.fra.srt").exists()
        assert result.output_sidecar_id == "sidecar_0002"
        assert result.input_version_id is None
        assert result.output_version_id is None
        # post_phase_b_sidecars captured the new hash + path.
        assert "sidecar_0002" in media_ctx.post_phase_b_sidecars

    def test_apply_extract_argv_uses_probed_language_match_index(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"s" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        # Probe stub returns index 1 (i.e. the SECOND subtitle stream
        # matches "fra"), so the argv must contain 0:s:1.
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler._probe_subtitle_index_for_language",
            lambda ctx, path, lang: 1,
        )
        entry = _atomic_entry(
            event_id="ev_xs_001",
            action=TimelineActionName.EXTRACT_SUBTITLE,
            target="a0",
            state_delta={
                "sidecar_id": "sidecar_0002",
                "sidecar_path": "x.fra.srt",
                "language": "fra",
                "input_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        assert "-map" in argv
        assert argv[argv.index("-map") + 1] == "0:s:1"
        # ffmpeg 8.x rejects the legacy metadata stream-specifier form;
        # make sure we don't regress.
        joined = " ".join(argv)
        assert "0:s:m:language" not in joined

    def test_apply_extract_argv_falls_back_to_track_0_on_lang_miss(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"s" * 100)
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version=ffmpeg_version,
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1,
                ),
                "",
            )

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        # Probe stub returns 0 — fallback path (no language matched).
        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler._probe_subtitle_index_for_language",
            lambda ctx, path, lang: 0,
        )
        entry = _atomic_entry(
            event_id="ev_xs_002",
            action=TimelineActionName.EXTRACT_SUBTITLE,
            target="a0",
            state_delta={
                "sidecar_id": "sidecar_0003",
                "sidecar_path": "x.deu.srt",
                "language": "deu",
                "input_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        assert argv[argv.index("-map") + 1] == "0:s:0"


def _subtitle_asset(asset_id: str = "a0") -> Asset:
    return Asset.model_validate(
        {
            "id": asset_id,
            "role": "primary_video",
            "container": "mkv",
            "duration_seconds": 2.0,
            "video": {"source": "color_bars", "codec": "h264", "resolution": "hd"},
            "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
            "subtitles": [{"codec": "srt", "language": "eng", "mode": "sidecar"}],
        }
    )


class TestApplyUpdateSidecar:
    def test_update_sidecar_subtitle_regenerates_bytes(self, tmp_path):
        # Asset declared with a subtitle so ctx can find duration_seconds.
        asset = _subtitle_asset()
        # Pre-populate the sidecar file.
        (tmp_path / "a0.eng.srt").write_bytes(b"old")
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": asset},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
            live_sidecars={"sidecar_0001": LiveSubtitleSidecar(asset_id="a0", language="eng")},
        )
        entry = _atomic_entry(
            event_id="ev_us_001",
            action=TimelineActionName.UPDATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_id": "sidecar_0001",
                "sidecar_path": "a0.eng.srt",
            },
        )
        result = apply_media_action(ctx, entry)
        new_bytes = (tmp_path / "a0.eng.srt").read_bytes()
        assert new_bytes != b"old"
        assert b"00:00:00,000" in new_bytes
        assert result.output_sidecar_id == "sidecar_0001"
        assert result.tool_invocation_index is None  # subtitle is pure Python
        assert "sidecar_0001" in ctx.post_phase_b_sidecars

    def test_update_resolves_sidecar_created_earlier_in_same_walk(self, tmp_path):
        """create_sidecar -> update_sidecar resolves from the live registry.

        WHY: the sidecar may never survive to the final manifest (a later
        remove/embed drops it), so update_sidecar must read the metadata a
        create_sidecar dispatch recorded, not the final manifest. This is the
        core of issue #112.
        """
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": _subtitle_asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        create = _atomic_entry(
            event_id="ev_cs_001",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.eng.srt",
                "sidecar_id": "sidecar_live",
                "language": "eng",
                "kind": "subtitle",
            },
        )
        apply_media_action(ctx, create)
        created_bytes = (tmp_path / "a0.eng.srt").read_bytes()
        update = _atomic_entry(
            event_id="ev_us_002",
            action=TimelineActionName.UPDATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_id": "sidecar_live",
                "sidecar_path": "a0.eng.srt",
            },
        )
        result = apply_media_action(ctx, update)
        assert result.output_sidecar_id == "sidecar_live"
        assert (tmp_path / "a0.eng.srt").read_bytes() != created_bytes

    def test_double_update_on_created_sidecar(self, tmp_path):
        """create -> update -> update both resolve and produce distinct bytes."""
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": _subtitle_asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_cs_001",
                action=TimelineActionName.CREATE_SIDECAR,
                target="a0",
                state_delta={
                    "sidecar_path": "a0.eng.srt",
                    "sidecar_id": "sidecar_live",
                    "language": "eng",
                    "kind": "subtitle",
                },
            ),
        )
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_us_001",
                action=TimelineActionName.UPDATE_SIDECAR,
                target="a0",
                state_delta={"sidecar_id": "sidecar_live", "sidecar_path": "a0.eng.srt"},
            ),
        )
        first = (tmp_path / "a0.eng.srt").read_bytes()
        result = apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_us_002",
                action=TimelineActionName.UPDATE_SIDECAR,
                target="a0",
                state_delta={"sidecar_id": "sidecar_live", "sidecar_path": "a0.eng.srt"},
            ),
        )
        assert result.output_sidecar_id == "sidecar_live"
        assert (tmp_path / "a0.eng.srt").read_bytes() != first

    def test_update_resolves_extracted_sidecar(self, monkeypatch, tmp_path):
        """extract_subtitle -> update_sidecar resolves from the live registry.

        extract_subtitle also allocates a fresh sidecar that may not survive to
        the final manifest, so it must register live metadata too.
        """
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": _subtitle_asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        (tmp_path / "a0.mkv").write_bytes(b"asset")

        def fake_probe_index(_ctx, _input, _language):
            return 0

        def fake_ffmpeg(argv, **_kwargs):
            Path(argv[-1]).write_bytes(b"extracted srt")
            return (
                ToolInvocation(
                    tool="ffmpeg",
                    version="7.0",
                    command=list(argv),
                    exit_code=0,
                    duration_ns=1,
                ),
                "",
            )

        monkeypatch.setattr(media_module, "_probe_subtitle_index_for_language", fake_probe_index)
        monkeypatch.setattr(media_module, "run_ffmpeg", fake_ffmpeg)
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_xs_001",
                action=TimelineActionName.EXTRACT_SUBTITLE,
                target="a0",
                state_delta={
                    "sidecar_id": "sidecar_extract",
                    "sidecar_path": "a0.deu.srt",
                    "language": "deu",
                    "input_path": "a0.mkv",
                },
            ),
        )
        result = apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_us_001",
                action=TimelineActionName.UPDATE_SIDECAR,
                target="a0",
                state_delta={"sidecar_id": "sidecar_extract", "sidecar_path": "a0.deu.srt"},
            ),
        )
        assert result.output_sidecar_id == "sidecar_extract"
        assert b"00:00:00,000" in (tmp_path / "a0.deu.srt").read_bytes()

    def test_update_unknown_sidecar_raises(self, tmp_path):
        """A corrupt journal that updates a never-created sidecar still fails."""
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": _subtitle_asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        entry = _atomic_entry(
            event_id="ev_us_001",
            action=TimelineActionName.UPDATE_SIDECAR,
            target="a0",
            state_delta={"sidecar_id": "sidecar_ghost", "sidecar_path": "a0.eng.srt"},
        )
        with pytest.raises(MediaActionError, match="not a live sidecar"):
            apply_media_action(ctx, entry)

    def test_update_preserves_authored_encoding(self, tmp_path):
        """create_sidecar utf16_le -> update_sidecar keeps UTF-16-LE bytes."""
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": _subtitle_asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_cs_001",
                action=TimelineActionName.CREATE_SIDECAR,
                target="a0",
                state_delta={
                    "sidecar_path": "a0.eng.srt",
                    "sidecar_id": "sidecar_live",
                    "language": "eng",
                    "kind": "subtitle",
                    "encoding": "utf16_le",
                },
            ),
        )
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_us_002",
                action=TimelineActionName.UPDATE_SIDECAR,
                target="a0",
                state_delta={"sidecar_id": "sidecar_live", "sidecar_path": "a0.eng.srt"},
            ),
        )
        updated = (tmp_path / "a0.eng.srt").read_bytes()
        # Still decodes as UTF-16-LE (would raise / mis-decode if reverted to UTF-8).
        assert "00:00:00,000" in updated.decode("utf-16-le")

    def test_update_preserves_authored_nfo_body(self, tmp_path):
        """create_sidecar nfo body -> update_sidecar re-emits the exact body."""
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": _subtitle_asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_cs_001",
                action=TimelineActionName.CREATE_SIDECAR,
                target="a0",
                state_delta={
                    "sidecar_path": "a0.nfo",
                    "sidecar_id": "sidecar_nfo",
                    "language": None,
                    "kind": "nfo",
                    "body": "<movie>AUTHORED</movie>",
                },
            ),
        )
        apply_media_action(
            ctx,
            _atomic_entry(
                event_id="ev_us_002",
                action=TimelineActionName.UPDATE_SIDECAR,
                target="a0",
                state_delta={"sidecar_id": "sidecar_nfo", "sidecar_path": "a0.nfo"},
            ),
        )
        assert (tmp_path / "a0.nfo").read_bytes() == b"<movie>AUTHORED</movie>"


class TestApplyCreateSidecar:
    """Sprint 7 routing fix: create_sidecar lives in media.py and dispatches per-kind.

    Adversarial-review finding #1 — the prior phase-B helper wrote SRT
    bytes unconditionally, so ``Quasar.poster.png`` and ``Quasar.nfo``
    shipped with subtitle contents on disk. These tests pin each kind's
    actual byte signature.
    """

    @staticmethod
    def _asset(asset_id: str = "a0") -> Asset:
        return Asset.model_validate(
            {
                "id": asset_id,
                "role": "primary_video",
                "container": "mkv",
                "duration_seconds": 2.0,
                "video": {"source": "color_bars", "codec": "h264", "resolution": "hd"},
                "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
                "subtitles": [],
            }
        )

    def test_subtitle_kind_writes_srt_bytes(self, tmp_path):
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": self._asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        entry = _atomic_entry(
            event_id="ev_cs_sub",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.eng.srt",
                "sidecar_id": "sidecar_sub",
                "language": "eng",
                "kind": "subtitle",
            },
        )
        result = apply_media_action(ctx, entry)
        body = (tmp_path / "a0.eng.srt").read_bytes()
        # SRT cue format includes the HH:MM:SS,mmm timestamp header.
        assert b"00:00:00,000" in body
        assert b"-->" in body
        assert result.output_sidecar_id == "sidecar_sub"
        assert result.tool_invocation_index is None
        assert "sidecar_sub" in ctx.post_phase_b_sidecars

    def test_nfo_kind_writes_xml_bytes(self, tmp_path):
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": self._asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        entry = _atomic_entry(
            event_id="ev_cs_nfo",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.nfo",
                "sidecar_id": "sidecar_nfo",
                "language": None,
                "kind": "nfo",
            },
        )
        result = apply_media_action(ctx, entry)
        body = (tmp_path / "a0.nfo").read_text()
        assert body.lstrip().startswith('<?xml version="1.0"')
        assert "<movie>" in body
        assert "sidecar_nfo" in body
        assert result.tool_invocation_index is None
        assert "sidecar_nfo" in ctx.post_phase_b_sidecars

    def test_poster_kind_invokes_ffmpeg_and_writes_png(self, monkeypatch, tmp_path):
        png_magic = b"\x89PNG\r\n\x1a\n"
        png_bytes = png_magic + b"stub-png-body"

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            Path(argv[-1]).write_bytes(png_bytes)
            invocation = ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=0,
                duration_ns=1000,
            )
            return invocation, ""

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": self._asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        entry = _atomic_entry(
            event_id="ev_cs_poster",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.poster.png",
                "sidecar_id": "sidecar_poster",
                "language": None,
                "kind": "poster",
            },
        )
        result = apply_media_action(ctx, entry)
        on_disk = (tmp_path / "a0.poster.png").read_bytes()
        assert on_disk.startswith(png_magic)
        assert result.tool_invocation_index is not None
        assert result.tool_invocation_index == 0
        assert ctx.invocations[0].tool == "ffmpeg"
        assert "sidecar_poster" in ctx.post_phase_b_sidecars

    def test_poster_kind_preserves_authoring_knob_enums(self, monkeypatch, tmp_path):
        captured_argv: list[str] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv[:] = argv
            Path(argv[-1]).write_bytes(b"webp")
            invocation = ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=0,
                duration_ns=1000,
            )
            return invocation, ""

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        ctx = self._ctx(tmp_path)
        entry = _atomic_entry(
            event_id="ev_cs_poster_webp",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.poster.webp",
                "sidecar_id": "sidecar_poster",
                "language": None,
                "kind": "poster",
                "media_type": "image",
                "image_format": "webp",
            },
        )

        apply_media_action(ctx, entry)

        sidecar = ctx.live_sidecars["sidecar_poster"]
        assert isinstance(sidecar, LivePosterSidecar)
        assert sidecar.media_type is SidecarMediaType.IMAGE
        assert sidecar.image_format is PosterImageFormat.WEBP
        assert "libwebp" in captured_argv

    def _ctx(self, tmp_path):
        return MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": self._asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )

    def test_subtitle_default_encoding_is_byte_identical(self, tmp_path):
        """With encoding omitted the bytes equal the unchanged UTF-8 SRT body."""
        ctx = self._ctx(tmp_path)
        entry = _atomic_entry(
            event_id="ev_cs_sub",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.eng.srt",
                "sidecar_id": "sidecar_sub",
                "language": "eng",
                "kind": "subtitle",
            },
        )
        apply_media_action(ctx, entry)
        on_disk = (tmp_path / "a0.eng.srt").read_bytes()
        expected = srt_payload(language="eng", duration_s=2.0, seed=42).encode("utf-8")
        assert on_disk == expected

    def test_subtitle_utf16_le_encoding(self, tmp_path):
        ctx = self._ctx(tmp_path)
        entry = _atomic_entry(
            event_id="ev_cs_sub",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.eng.srt",
                "sidecar_id": "sidecar_sub",
                "language": "eng",
                "kind": "subtitle",
                "encoding": "utf16_le",
            },
        )
        apply_media_action(ctx, entry)
        on_disk = (tmp_path / "a0.eng.srt").read_bytes()
        utf8 = srt_payload(language="eng", duration_s=2.0, seed=42).encode("utf-8")
        assert on_disk != utf8
        assert on_disk.decode("utf-16-le") == utf8.decode("utf-8")

    def test_nfo_body_written_verbatim(self, tmp_path):
        ctx = self._ctx(tmp_path)
        entry = _atomic_entry(
            event_id="ev_cs_nfo",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.nfo",
                "sidecar_id": "sidecar_nfo",
                "language": None,
                "kind": "nfo",
                "body": "<movie>INJECT</movie>",
            },
        )
        apply_media_action(ctx, entry)
        assert (tmp_path / "a0.nfo").read_bytes() == b"<movie>INJECT</movie>"

    def test_subtitle_live_sidecar_records_encoding(self, tmp_path):
        ctx = self._ctx(tmp_path)
        entry = _atomic_entry(
            event_id="ev_cs_sub",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.eng.srt",
                "sidecar_id": "sidecar_sub",
                "language": "eng",
                "kind": "subtitle",
                "encoding": "utf16_le",
            },
        )
        apply_media_action(ctx, entry)
        sidecar = ctx.live_sidecars["sidecar_sub"]
        assert isinstance(sidecar, LiveSubtitleSidecar)
        assert sidecar.encoding == "utf16_le"

    def test_poster_kind_ffmpeg_failure_raises_media_action_error(self, monkeypatch, tmp_path):
        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            invocation = ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=1,
                duration_ns=1000,
            )
            return invocation, "ffmpeg crashed"

        monkeypatch.setattr(
            "chaos_librarian.materializer.phase_b.media.handler.run_ffmpeg", fake_run
        )
        ctx = MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={"a0": self._asset()},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
        )
        entry = _atomic_entry(
            event_id="ev_cs_poster_fail",
            action=TimelineActionName.CREATE_SIDECAR,
            target="a0",
            state_delta={
                "sidecar_path": "a0.poster.png",
                "sidecar_id": "sidecar_poster",
                "language": None,
                "kind": "poster",
            },
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(ctx, entry)
        assert exc_info.value.action == TimelineActionName.CREATE_SIDECAR


def _recorded_probe_result(
    *,
    stdout: str = "",
    stderr_tail: str = "",
    returncode: int = 0,
    argv: list[str] | None = None,
    version: str = "7.1",
) -> RecordedToolResult:
    return RecordedToolResult(
        invocation=ToolInvocation(
            tool="ffprobe",
            version=version,
            command=list(argv or ["ffprobe"]),
            exit_code=returncode,
            duration_ns=1,
        ),
        stderr_tail=stderr_tail,
        stdout=stdout,
    )


class TestProbeSubtitleIndexForLanguage:
    """Covers media._probe_subtitle_index_for_language (#59, #61)."""

    def _ctx(self, tmp_path):
        return MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.1",
        )

    def test_probe_picks_matching_language_index(self, monkeypatch, tmp_path):
        # Two subtitle streams: eng then fra; ask for fra → expect index 1.
        payload = {
            "streams": [
                {"index": 2, "tags": {"language": "eng"}},
                {"index": 3, "tags": {"language": "fra"}},
            ]
        }

        def fake_run(argv, **kwargs):
            return _recorded_probe_result(
                stdout=json.dumps(payload),
                argv=argv,
                version=kwargs["version"],
            )

        monkeypatch.setattr(media_module, "run_recorded_tool", fake_run)
        ctx = self._ctx(tmp_path)
        idx = media_module._probe_subtitle_index_for_language(ctx, tmp_path / "x.mkv", "fra")
        assert idx == 1
        # #61: every probe call must be auditable via ctx.invocations.
        assert len(ctx.invocations) == 1
        assert ctx.invocations[0].tool == "ffprobe"
        assert ctx.invocations[0].exit_code == 0
        assert ctx.invocations[0].version == "7.1"

    def test_probe_falls_back_to_zero_when_language_missing(self, monkeypatch, tmp_path):
        payload = {
            "streams": [
                {"index": 2, "tags": {"language": "eng"}},
            ]
        }

        def fake_run(argv, **kwargs):
            return _recorded_probe_result(
                stdout=json.dumps(payload),
                argv=argv,
                version=kwargs["version"],
            )

        monkeypatch.setattr(media_module, "run_recorded_tool", fake_run)
        ctx = self._ctx(tmp_path)
        idx = media_module._probe_subtitle_index_for_language(ctx, tmp_path / "x.mkv", "deu")
        assert idx == 0
        assert len(ctx.invocations) == 1

    def test_probe_falls_back_to_zero_when_no_streams_key(self, monkeypatch, tmp_path):
        def fake_run(argv, **kwargs):
            return _recorded_probe_result(stdout="{}", argv=argv, version=kwargs["version"])

        monkeypatch.setattr(media_module, "run_recorded_tool", fake_run)
        ctx = self._ctx(tmp_path)
        idx = media_module._probe_subtitle_index_for_language(ctx, tmp_path / "x.mkv", "eng")
        assert idx == 0
        assert len(ctx.invocations) == 1

    def test_probe_nonzero_exit_raises_runtime_error(self, monkeypatch, tmp_path):
        def fake_run(argv, **kwargs):
            return _recorded_probe_result(
                stdout="",
                stderr_tail="boom",
                returncode=1,
                argv=argv,
                version=kwargs["version"],
            )

        monkeypatch.setattr(media_module, "run_recorded_tool", fake_run)
        ctx = self._ctx(tmp_path)
        with pytest.raises(RuntimeError, match="ffprobe"):
            media_module._probe_subtitle_index_for_language(ctx, tmp_path / "x.mkv", "eng")
        # #61: failed probes must still appear in the audit log so users
        # can see the exit_code that caused the materialize failure.
        assert len(ctx.invocations) == 1
        assert ctx.invocations[0].exit_code == 1
        assert ctx.invocations[0].tool == "ffprobe"


class TestApplyMediaActionIOErrorWrapping:
    """Adversarial-review finding #3: OSError from a handler must wrap.

    Without wrapping at the apply_media_action entry point, bare OSError
    propagates past the orchestrator's ``except MediaActionError`` clause
    and ``finalize_failure_phase_b`` never runs — leaving ``library/``
    half-mutated and the sentinel stuck at IN_PROGRESS.
    """

    def test_reencode_video_oserror_wraps_in_media_action_error(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"x" * 100)
        original_replace = Path.replace

        def boom_replace(self, target):
            if str(self).endswith(".tmp.42.mkv"):
                raise OSError(28, "No space left on device")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", boom_replace)
        entry = _atomic_entry(
            event_id="ev_io_rv",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "resolution": "sd",
                "codec": "h264",
                "input_path": "x.mkv",
                "output_path": "x.mkv",
            },
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)
        assert exc_info.value.event_id == "ev_io_rv"
        assert exc_info.value.action == TimelineActionName.REENCODE_VIDEO
        assert isinstance(exc_info.value.cause, OSError)

    def test_embed_subtitle_oserror_wraps_in_media_action_error(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        (tmp_path / "s.srt").write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nstub\n")
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"x" * 100)
        original_unlink = Path.unlink

        def boom_unlink(self, *args, **kwargs):
            if self.name == "s.srt":
                raise OSError(13, "Permission denied")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", boom_unlink)
        entry = _atomic_entry(
            event_id="ev_io_es",
            action=TimelineActionName.EMBED_SUBTITLE,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "input_path": "x.mkv",
                "output_path": "x.mkv",
                "embedded_sidecar_path": "s.srt",
                "embedded_sidecar_id": "sc0",
                "language": "eng",
                "kind": "subtitle",
            },
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)
        assert exc_info.value.event_id == "ev_io_es"
        assert exc_info.value.action == TimelineActionName.EMBED_SUBTITLE
        assert isinstance(exc_info.value.cause, OSError)

    def test_non_oserror_handler_failure_wraps_in_media_action_error(self, media_ctx, monkeypatch):
        def boom_handler(_ctx, _entry):
            raise KeyError("missing scenario asset")

        monkeypatch.setitem(
            media_module._HANDLERS,
            TimelineActionName.REENCODE_VIDEO,
            boom_handler,
        )
        entry = _atomic_entry(
            event_id="ev_contract_bug",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={"input_path": "x.mkv", "output_path": "x.mkv"},
        )

        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)

        assert exc_info.value.event_id == "ev_contract_bug"
        assert exc_info.value.action == TimelineActionName.REENCODE_VIDEO
        assert exc_info.value.asset_id == "a0"
        assert isinstance(exc_info.value.cause, KeyError)
