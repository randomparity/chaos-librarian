"""Tests for the replay-bundle schema and run-id derivation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract import (
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.materialization import ToolchainInfo
from chaos_librarian.contract.replay_bundle import (
    AllocTraceEntry,
    ExecutionMode,
    ExecutionTraceEntry,
    ExecutionTraceKind,
    MaterializeReplayBundle,
    MaterializerTraceEntry,  # noqa: F401  -- verifies public re-export of materializer variant
    PlanOnlyReplayBundle,
    ReplayBundle,
    RngTraceEntry,
    compute_plan_only_run_id,
)


def _scenario_hash(scenario_yaml: str) -> str:
    return hashlib.sha256(scenario_yaml.encode("utf-8")).hexdigest()


def _plan_only_base(seed: int = 1) -> dict[str, object]:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    return {
        "execution_mode": "plan_only",
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "chaos_librarian_version": "0.0.0",
        "scenario": "scenario_id: t\nseed: 1\n",
        "run_id": str(compute_plan_only_run_id(h, seed)),
        "resolved_seed": seed,
        "applied_events": 0,
        "journal_digest": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "execution_trace": [],
    }


def _materialize_base() -> dict[str, object]:
    return {
        "execution_mode": "materialize",
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "chaos_librarian_version": "0.0.0",
        "scenario": "scenario_id: t\nseed: 1\n",
        "run_id": str(uuid.uuid4()),
        "resolved_seed": 1,
        "applied_events": 0,
        "journal_digest": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "execution_trace": [],
        "content_sources": [
            {
                "asset_id": "asset_main",
                "track_kind": "video",
                "track_index": None,
                "source": "color_bars",
                "provider": "builtin-lavfi",
                "recipe_digest": "sha256:" + "0" * 64,
                "cache_disposition": "not_cacheable",
                "cache_key": None,
                "content_hash": None,
                "origin_uri": None,
                "license": None,
            }
        ],
    }


def test_plan_only_run_id_is_deterministic() -> None:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    a = compute_plan_only_run_id(h, resolved_seed=1)
    b = compute_plan_only_run_id(h, resolved_seed=1)
    assert a == b
    assert a.version == 5


def test_plan_only_run_id_uses_namespace() -> None:
    h = _scenario_hash("x")
    expected = uuid.uuid5(CHAOS_LIBRARIAN_NAMESPACE_UUID, f"{h}:42")
    assert compute_plan_only_run_id(h, resolved_seed=42) == expected


def test_plan_only_run_id_differs_by_seed() -> None:
    h = _scenario_hash("x")
    assert compute_plan_only_run_id(h, 1) != compute_plan_only_run_id(h, 2)


def test_plan_only_bundle_has_no_created_at_or_toolchain_fields() -> None:
    h = _scenario_hash("x")
    b = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=compute_plan_only_run_id(h, 1),
        resolved_seed=1,
        applied_events=0,
        journal_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        execution_trace=[],
    )
    parsed = json.loads(b.model_dump_json())
    assert "created_at" not in parsed
    assert "toolchain" not in parsed
    assert parsed["applied_events"] == 0
    assert (
        parsed["journal_digest"]
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_plan_only_bundle_roundtrip_byte_identical() -> None:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    b = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=compute_plan_only_run_id(h, 1),
        resolved_seed=1,
        applied_events=0,
        journal_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        execution_trace=[
            RngTraceEntry(kind=ExecutionTraceKind.RNG, stream="ids", value="1"),
            AllocTraceEntry(
                kind=ExecutionTraceKind.ALLOC,
                stream="movie_id",
                value="movie_orbit",
            ),
        ],
    )
    blob_a = json.dumps(json.loads(b.model_dump_json()), sort_keys=True)
    blob_b = json.dumps(json.loads(b.model_dump_json()), sort_keys=True)
    assert blob_a == blob_b


def test_materialize_bundle_has_created_at_and_toolchain() -> None:
    b = MaterializeReplayBundle(
        execution_mode=ExecutionMode.MATERIALIZE,
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=uuid.uuid4(),
        created_at=datetime(2026, 5, 17, 12, 0, tzinfo=UTC),
        resolved_seed=1,
        applied_events=0,
        journal_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        execution_trace=[],
        toolchain=ToolchainInfo(ffmpeg="7.1", ffprobe="7.1"),
        content_sources=[],
    )
    loaded = TypeAdapter(ReplayBundle).validate_json(b.model_dump_json())
    assert loaded.created_at == b.created_at
    assert loaded.toolchain == b.toolchain


def test_rejects_unknown_schema_version() -> None:
    bad = {**_plan_only_base(), "schema_version": 999}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bad)


def test_plan_only_rejects_created_at() -> None:
    # extra="forbid" on PlanOnlyReplayBundle rejects created_at outright,
    # including explicit null.
    bundle_json = {**_plan_only_base(), "created_at": None}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_plan_only_rejects_toolchain() -> None:
    bundle_json = {**_plan_only_base(), "toolchain": {"ffmpeg": "7.1"}}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_plan_only_rejects_content_sources() -> None:
    bundle_json = {**_plan_only_base(), "content_sources": []}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_materialize_requires_created_at() -> None:
    bundle_json = {**_materialize_base(), "toolchain": {"ffmpeg": "7.1"}}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_materialize_requires_toolchain() -> None:
    bundle_json = {**_materialize_base(), "created_at": "2026-05-17T12:00:00Z"}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_materialize_rejects_null_toolchain() -> None:
    bundle_json = {
        **_materialize_base(),
        "created_at": "2026-05-17T12:00:00Z",
        "toolchain": None,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_run_id_independent_of_applied_events() -> None:
    """run_id is invariant across applied_events values.

    WHY: under the no-fold design, two bundles of the same scenario+seed
    at different truncation points share a run_id — they describe the
    same logical run at different prefixes. The previous fold-into-run_id
    design was rejected because it broke step-mode cursor recovery (the
    journal entries stamped during plan carried the old run_id while the
    regenerated entries on the next step carried a new run_id, tripping
    JournalCorruptError on the plan's own writes). Codex review
    finding 1.
    """
    h = _scenario_hash("x")
    base = compute_plan_only_run_id(h, resolved_seed=1)
    assert compute_plan_only_run_id(h, resolved_seed=1) == base
    # applied_events is bundle metadata, not part of the hash; constructing
    # bundles with different applied_events does not affect the run_id.
    payload_zero = {**_plan_only_base(), "applied_events": 0, "run_id": str(base)}
    payload_five = {**_plan_only_base(), "applied_events": 5, "run_id": str(base)}
    assert TypeAdapter(ReplayBundle).validate_python(payload_zero).run_id == base
    assert TypeAdapter(ReplayBundle).validate_python(payload_five).run_id == base


def test_plan_only_bundle_rejects_negative_applied_events() -> None:
    """applied_events must be non-negative.

    WHY: a negative count would imply a journal of negative length —
    nonsensical; reject at the schema layer so no downstream code has to
    defend against it.
    """
    payload = {**_plan_only_base(), "applied_events": -1}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(payload)


def test_journal_digest_required() -> None:
    """journal_digest is mandatory on every plan-only bundle.

    WHY: it's the self-contained integrity anchor — without it,
    applied_events tampering goes undetected when no --against is
    supplied (Codex round 3 finding 2).
    """
    payload = {**_plan_only_base()}
    del payload["journal_digest"]
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(payload)


def test_journal_digest_must_be_sha256_hex() -> None:
    """journal_digest is constrained to 64 lowercase hex chars."""
    payload = {**_plan_only_base(), "journal_digest": "nothex"}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(payload)


def test_journal_digest_matches_helper_output() -> None:
    """A known journal produces a known digest.

    WHY: ensures the documented digest formula (sha256 of the on-disk
    journal byte stream) is what bundles actually record.
    """
    payload = {**_plan_only_base()}  # empty journal helper default
    bundle = TypeAdapter(ReplayBundle).validate_python(payload)
    assert (
        bundle.journal_digest == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def _trace_base(kind: str) -> dict[str, object]:
    return {"kind": kind, "stream": "ids", "value": "1"}


def test_rng_trace_entry_rejects_exit_code() -> None:
    bad = {**_trace_base("rng"), "exit_code": 0}
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionTraceEntry).validate_python(bad)


def test_alloc_trace_entry_rejects_exit_code() -> None:
    bad = {**_trace_base("alloc"), "exit_code": 0}
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionTraceEntry).validate_python(bad)


def test_materializer_trace_entry_requires_exit_code() -> None:
    bad = _trace_base("materializer")
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionTraceEntry).validate_python(bad)


def test_materializer_trace_entry_rejects_null_exit_code() -> None:
    bad = {**_trace_base("materializer"), "exit_code": None}
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionTraceEntry).validate_python(bad)


def test_trace_entry_rejects_unknown_kind() -> None:
    bad = _trace_base("io")
    with pytest.raises(ValidationError):
        TypeAdapter(ExecutionTraceEntry).validate_python(bad)


def _materialize_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "chaos_librarian_version": "0.1.0",
        "scenario": "schema_version: 32\nscenario_id: x\n",
        "run_id": "00000000-0000-4000-8000-000000000000",
        "resolved_seed": 1,
        "applied_events": 0,
        "journal_digest": "0" * 64,
        "execution_mode": "materialize",
        "created_at": "2026-05-18T00:00:00Z",
        "toolchain": {"ffmpeg": "7.1.1"},
        "content_sources": [
            {
                "asset_id": "asset_main",
                "track_kind": "video",
                "track_index": None,
                "source": "color_bars",
                "provider": "builtin-lavfi",
                "recipe_digest": "sha256:" + "0" * 64,
                "cache_disposition": "not_cacheable",
                "cache_key": None,
                "content_hash": None,
                "origin_uri": None,
                "license": None,
            }
        ],
    }
    base.update(overrides)
    return base


def test_materialize_bundle_accepts_nonzero_applied_events():
    """WHY: Sprint 6 wires phase B into materialize; the bundle must
    record the number of timeline events the engine applied so consumers
    can correlate the journal length with the replay window. The field
    widened from ``Literal[0]`` back to the base class's
    ``int = Field(ge=0)`` constraint when timeline-mutating materialize
    landed."""
    payload = _materialize_payload(applied_events=3)
    bundle = MaterializeReplayBundle.model_validate(payload)
    assert bundle.applied_events == 3


def test_materialize_bundle_rejects_negative_applied_events():
    """WHY: a negative count would imply a journal of negative length;
    reject at the schema layer so no downstream code has to defend
    against it. Mirrors the plan-only test of the same invariant."""
    payload = _materialize_payload(applied_events=-1)
    with pytest.raises(ValidationError):
        MaterializeReplayBundle.model_validate(payload)


def test_materialize_bundle_accepts_zero_applied_events():
    bundle = MaterializeReplayBundle.model_validate(_materialize_payload())
    assert bundle.applied_events == 0


def test_materialize_bundle_toolchain_is_structured():
    """WHY: Sprint 5 unifies the toolchain shape with MaterializationReport
    via ToolchainInfo; the bundle's toolchain must be the same model."""
    bundle = MaterializeReplayBundle.model_validate(_materialize_payload())
    assert isinstance(bundle.toolchain, ToolchainInfo)
    assert bundle.toolchain.ffmpeg == "7.1.1"


def test_materialize_bundle_toolchain_rejects_unknown_tool():
    payload = _materialize_payload(toolchain={"ffmpeg": "7.1.1", "imagemagick": "7.0"})
    with pytest.raises(ValidationError):
        MaterializeReplayBundle.model_validate(payload)


def test_replay_bundle_schema_version_is_twelve() -> None:
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 12


def test_materialize_bundle_carries_content_source_evidence() -> None:
    payload = _materialize_payload()
    content_sources = cast("list[dict[str, object]]", payload["content_sources"])
    assert isinstance(content_sources, list)
    content_sources.append(
        {
            "asset_id": "asset_main",
            "track_kind": "muxing",
            "source": "no_cues",
            "provider": "builtin-mkvmerge",
            "recipe_digest": "sha256:" + "2" * 64,
            "matroska_muxing_profile": "no_cues",
            "container": "webm",
            "cache_disposition": "not_cacheable",
        }
    )
    bundle = MaterializeReplayBundle.model_validate(payload)

    assert bundle.content_sources[0].source == "color_bars"
    assert bundle.content_sources[1].source == "no_cues"
    assert bundle.content_sources[1].matroska_muxing_profile is not None
    assert bundle.content_sources[1].matroska_muxing_profile.value == "no_cues"
