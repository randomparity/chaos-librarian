"""Plans retain structural intent without inventing encoded byte offsets."""

import pytest

from chaos_librarian.contract.manifest import ManifestVersion
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.engine.version_history import derive_version_history
from tests.engine.conftest import _engine_event_context
from tests.engine.test_events_media import _RUN_ID, _scenario


@pytest.mark.parametrize(
    ("action", "key", "value"),
    [
        ("corrupt_container_header", "region", "mp4_moov"),
        ("corrupt_container_header", "region", "mkv_cues"),
        ("truncate_file", "boundary", "mp3_after_16_frames"),
    ],
)
def test_engine_preserves_unresolved_structural_intent(action: str, key: str, value: str) -> None:
    scenario = _scenario(
        [{"id": "damage", "at": "1s", "action": action, "target": "a0", key: value}],
        profiles=["malformed-media"],
    )
    ids = IdAllocator(TraceRecorder())
    state = build_initial_state(scenario, ids)
    (entry,) = apply_event(
        state,
        resolve_timeline(scenario)[0],
        ids,
        _engine_event_context("media", run_id=_RUN_ID, resolved_seed=42),
    )
    assert entry.state_delta[key] == value
    version = state.versions[state.version_id_for_asset("a0")]
    assert version.corruption is not None
    assert version.corruption.metadata == {key: value}
    assert version.corruption.byte_start is None
    assert version.corruption.byte_count is None
    assert ManifestVersion.model_validate(version.model_dump()) == version
    assert derive_version_history("a0", [entry])[0].state_delta_summary[key] == value
    if key == "boundary":
        assert entry.state_delta["keep_bytes"] is None
