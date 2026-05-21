"""Tests for materializer/media.py."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import Asset, TimelineActionName
from chaos_librarian.materializer import media as media_module
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.media import (
    _MEDIA_ACTIONS,
    _STDLIB_ACTIONS,
    SUPPORTED_S7_ACTIONS,
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
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

    def test_apply_reencode_audio_unknown_channel_layout_raises(
        self, media_ctx, monkeypatch, tmp_path
    ):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        # ffmpeg must NOT be invoked: assert by failing the fake.
        ffmpeg_calls: list[int] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            ffmpeg_calls.append(1)
            raise AssertionError("ffmpeg invoked for unknown channel layout")

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
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


class TestApplyExtractSubtitle:
    def test_apply_extract_writes_srt_at_to_path(self, media_ctx, monkeypatch, tmp_path):
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"s" * 100)
        monkeypatch.setattr(
            "chaos_librarian.materializer.media._probe_subtitle_index_for_language",
            lambda path, lang: 0,
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        # Probe stub returns index 1 (i.e. the SECOND subtitle stream
        # matches "fra"), so the argv must contain 0:s:1.
        monkeypatch.setattr(
            "chaos_librarian.materializer.media._probe_subtitle_index_for_language",
            lambda path, lang: 1,
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        # Probe stub returns 0 — fallback path (no language matched).
        monkeypatch.setattr(
            "chaos_librarian.materializer.media._probe_subtitle_index_for_language",
            lambda path, lang: 0,
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


class TestApplyUpdateSidecar:
    def test_update_sidecar_subtitle_regenerates_bytes(self, monkeypatch, tmp_path):
        # Asset declared with a subtitle so ctx can find duration_seconds.
        asset = Asset.model_validate(
            {
                "id": "a0",
                "role": "primary_video",
                "container": "mkv",
                "duration_seconds": 2.0,
                "video": {"source": "color_bars", "codec": "h264", "resolution": "hd"},
                "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
                "subtitles": [{"codec": "srt", "language": "eng", "mode": "sidecar"}],
            }
        )
        sidecar = ManifestSidecar(
            id="sidecar_0001",
            asset_id="a0",
            kind="subtitle",
            path="a0.eng.srt",
            language="eng",
        )
        # Pre-populate the sidecar file.
        (tmp_path / "a0.eng.srt").write_bytes(b"old")
        ctx = _MediaContext(
            library_root=tmp_path,
            scenario_assets={"a0": asset},
            resolved_seed=42,
            ffmpeg_version="7.0",
            ffprobe_version="7.0",
            sidecar_lookup=lambda _sid: sidecar,
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
        ctx = _MediaContext(
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
        ctx = _MediaContext(
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        ctx = _MediaContext(
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

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        ctx = _MediaContext(
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


class _FakeCompleted:
    def __init__(self, *, stdout: str = "", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestProbeSubtitleIndexForLanguage:
    """Covers media._probe_subtitle_index_for_language (#59)."""

    def test_probe_picks_matching_language_index(self, monkeypatch, tmp_path):
        # Two subtitle streams: eng then fra; ask for fra → expect index 1.
        payload = {
            "streams": [
                {"index": 2, "tags": {"language": "eng"}},
                {"index": 3, "tags": {"language": "fra"}},
            ]
        }

        def fake_run(argv, **_kwargs):
            return _FakeCompleted(stdout=json.dumps(payload))

        monkeypatch.setattr(media_module.subprocess, "run", fake_run)
        idx = media_module._probe_subtitle_index_for_language(tmp_path / "x.mkv", "fra")
        assert idx == 1

    def test_probe_falls_back_to_zero_when_language_missing(self, monkeypatch, tmp_path):
        payload = {
            "streams": [
                {"index": 2, "tags": {"language": "eng"}},
            ]
        }

        def fake_run(argv, **_kwargs):
            return _FakeCompleted(stdout=json.dumps(payload))

        monkeypatch.setattr(media_module.subprocess, "run", fake_run)
        idx = media_module._probe_subtitle_index_for_language(tmp_path / "x.mkv", "deu")
        assert idx == 0

    def test_probe_falls_back_to_zero_when_no_streams_key(self, monkeypatch, tmp_path):
        def fake_run(argv, **_kwargs):
            return _FakeCompleted(stdout="{}")

        monkeypatch.setattr(media_module.subprocess, "run", fake_run)
        idx = media_module._probe_subtitle_index_for_language(tmp_path / "x.mkv", "eng")
        assert idx == 0

    def test_probe_nonzero_exit_raises_runtime_error(self, monkeypatch, tmp_path):
        def fake_run(argv, **_kwargs):
            return _FakeCompleted(stdout="", stderr="boom", returncode=1)

        monkeypatch.setattr(media_module.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError, match="ffprobe"):
            media_module._probe_subtitle_index_for_language(tmp_path / "x.mkv", "eng")


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


def test_media_actions_constant_contents():
    assert (
        frozenset(
            {
                TimelineActionName.REENCODE_VIDEO,
                TimelineActionName.REENCODE_AUDIO,
                TimelineActionName.REMUX_CONTAINER,
                TimelineActionName.EDIT_METADATA,
                TimelineActionName.EMBED_SUBTITLE,
                TimelineActionName.EXTRACT_SUBTITLE,
                TimelineActionName.UPDATE_SIDECAR,
                TimelineActionName.CREATE_SIDECAR,
            }
        )
        == _MEDIA_ACTIONS
    )


def test_stdlib_actions_constant_includes_remove_sidecar():
    # Sprint 6's set plus REMOVE_SIDECAR (stdlib op), minus CREATE_SIDECAR
    # (moved to _MEDIA_ACTIONS in Sprint 7).
    assert TimelineActionName.REMOVE_SIDECAR in _STDLIB_ACTIONS
    assert TimelineActionName.MOVE_ASSET in _STDLIB_ACTIONS  # from S6
    assert TimelineActionName.CREATE_SIDECAR not in _STDLIB_ACTIONS


def test_supported_s7_actions_union():
    assert SUPPORTED_S7_ACTIONS == _STDLIB_ACTIONS | _MEDIA_ACTIONS
    # add_file remains excluded.
    assert TimelineActionName.ADD_FILE not in SUPPORTED_S7_ACTIONS
