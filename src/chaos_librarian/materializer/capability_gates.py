"""Scenario-dependent materialization capability gates."""

from __future__ import annotations

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.materializer.errors import CapabilityGateError
from chaos_librarian.materializer.preflight import iter_assets

__all__ = ["assert_capable_for_hdr_video"]


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
