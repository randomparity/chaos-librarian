"""WebM capability gate must skip import assets (ADR 0012, issue #105).

Why: an imported ``.webm`` asset materializes as a byte copy of the
scenario-bundled original — no libvpx-vp9 synthesis happens — so the
container-only preflight gate would wrongly abort runs on machines whose
FFmpeg lacks vp9. Synthesized webm assets keep the gate.
"""

from __future__ import annotations

import pytest

from chaos_librarian.materializer.errors import CapabilityGateError
from chaos_librarian.materializer.preparation.capability_gates import (
    assert_capable_for_webm_video,
)
from tests.materializer.test_capability_gates import _capabilities, _scenario_with_asset


def test_webm_gate_skips_import_asset() -> None:
    scenario = _scenario_with_asset(
        {
            "id": "imp_webm",
            "role": "main",
            "container": "webm",
            "duration_seconds": 1.0,
            "import_source": {"path": "media/clip.webm"},
        }
    )
    # No raise: a copied .webm never invokes libvpx-vp9.
    assert_capable_for_webm_video(scenario, _capabilities(materialize_webm_video=False))


def test_webm_gate_still_gates_synthesized_webm() -> None:
    scenario = _scenario_with_asset(
        {
            "id": "asset_webm",
            "role": "main",
            "container": "webm",
            "duration_seconds": 1.0,
            "video": {"source": "color_bars", "codec": "vp9", "resolution": "sd"},
        }
    )
    with pytest.raises(CapabilityGateError):
        assert_capable_for_webm_video(scenario, _capabilities(materialize_webm_video=False))
