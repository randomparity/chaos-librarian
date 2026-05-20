"""Tests for materializer/media.py."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.media import (
    _MediaContext,
    _subtitle_codec_for_container,
    apply_media_action,
)


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
    ctx = _MediaContext(
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
    return _MediaContext(
        library_root=tmp_path,
        scenario_assets={},
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

    monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
    monkeypatch.setattr("chaos_librarian.materializer.media.probe_file", fake_probe)


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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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
        assert argv[argv.index("-ac") + 1] == "stereo"


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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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
