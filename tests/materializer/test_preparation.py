"""Tests for shared materializer preparation helpers."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.materializer import preparation as prep_mod
from chaos_librarian.validation import prepare_run_input

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def test_prepare_materializer_run_input_uses_existing_input_and_plan_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
    monkeypatch.setattr(prep_mod, "detect_capabilities", lambda: caps)
    run_input = prepare_run_input(FIXTURE_DIR / "identity-move-rename.yaml")

    prepared = prep_mod.prepare_materializer_run_input(
        run_input,
        validation_failure_message="scenario failed semantic validation",
        validation_payload_exclude_none=True,
        run_id_override=RUN_ID,
        applied_events_override=0,
    )

    assert prepared.run_input is run_input
    assert prepared.caps == caps
    assert prepared.run_id == RUN_ID
    assert prepared.plan_artifacts.replay_bundle.run_id == RUN_ID
    assert prepared.plan_artifacts.replay_bundle.applied_events == 0
    assert prepared.validation_report.ok is True
