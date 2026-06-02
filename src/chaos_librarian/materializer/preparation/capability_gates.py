"""Scenario-dependent materialization capability gates."""

from __future__ import annotations

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.scenario import AudioSource, Scenario
from chaos_librarian.materializer.errors import CapabilityGateError
from chaos_librarian.materializer.preparation.preflight import iter_assets

__all__ = [
    "assert_capable_for_audio_recipes",
    "assert_capable_for_hdr_video",
    "assert_capable_for_matroska_muxing_profiles",
    "assert_capable_for_resolution_switch_video",
    "assert_capable_for_webm_video",
]


def assert_capable_for_audio_recipes(scenario: Scenario, caps: Capabilities) -> None:
    """Raise before run-dir allocation when scenario needs optional audio recipes."""
    for asset in iter_assets(scenario):
        for audio in asset.audio:
            if audio.source is not AudioSource.NOISE:
                continue
            if caps.ready_for.materialize_audio_recipes:
                return
            raise CapabilityGateError(
                "audio noise materialization requires FFmpeg with the anoisesrc filter",
                asset_id=asset.id,
                field="ready_for.materialize_audio_recipes",
                payload={
                    "capability": "ready_for.materialize_audio_recipes",
                    "required_filter": "anoisesrc",
                    "audio_source": audio.source.value,
                    "noise_color": None if audio.noise_color is None else audio.noise_color.value,
                    "sample_rate": audio.sample_rate,
                    "sample_format": (
                        None if audio.sample_format is None else audio.sample_format.value
                    ),
                },
            )


def assert_capable_for_matroska_muxing_profiles(
    scenario: Scenario,
    caps: Capabilities,
) -> None:
    """Raise before run-dir allocation when a muxing profile needs mkvmerge."""
    for asset in iter_assets(scenario):
        if asset.matroska_muxing_profile is None:
            continue
        if caps.ready_for.materialize_matroska_muxing_profiles:
            return
        raise CapabilityGateError(
            "Matroska/WebM muxing profiles require mkvmerge",
            asset_id=asset.id,
            field="ready_for.materialize_matroska_muxing_profiles",
            payload={
                "capability": "ready_for.materialize_matroska_muxing_profiles",
                "required_tool": "mkvmerge",
            },
        )


def assert_capable_for_webm_video(scenario: Scenario, caps: Capabilities) -> None:
    """Raise before run-dir allocation when WebM needs libvpx-vp9."""
    for asset in iter_assets(scenario):
        if asset.container != "webm":
            continue
        if caps.ready_for.materialize_webm_video:
            return
        raise CapabilityGateError(
            "WebM materialization requires FFmpeg with libvpx-vp9",
            asset_id=asset.id,
            field="ready_for.materialize_webm_video",
            payload={
                "capability": "ready_for.materialize_webm_video",
                "required_encoder": "libvpx-vp9",
            },
        )


def assert_capable_for_hdr_video(scenario: Scenario, caps: Capabilities) -> None:
    """Raise before run-dir allocation when scenario needs HDR signaling."""
    for asset in iter_assets(scenario):
        if asset.video is None or asset.video.hdr_mode is None:
            continue
        if caps.ready_for.materialize_hdr_video:
            return
        raise CapabilityGateError(
            "HDR video materialization requires FFmpeg with libx265 10-bit and setparams",
            asset_id=asset.id,
            field="ready_for.materialize_hdr_video",
            payload={
                "capability": "ready_for.materialize_hdr_video",
                "required_encoder": "libx265",
                "required_filter": "setparams",
                "required_pixel_format": "yuv420p10le",
                "hdr_mode": asset.video.hdr_mode.value,
            },
        )


def assert_capable_for_resolution_switch_video(
    scenario: Scenario,
    caps: Capabilities,
) -> None:
    """Raise before run-dir allocation when scenario needs resolution switching."""
    for asset in iter_assets(scenario):
        if asset.video is None or asset.video.resolution_sequence is None:
            continue
        if caps.ready_for.materialize_resolution_switch_video:
            return
        raise CapabilityGateError(
            "resolution-switch video materialization requires FFmpeg with libx264",
            asset_id=asset.id,
            field="ready_for.materialize_resolution_switch_video",
            payload={
                "capability": "ready_for.materialize_resolution_switch_video",
                "required_encoder": "libx264",
                "resolution_sequence": asset.video.resolution_sequence.value,
            },
        )
