"""Tests for the replay-bundle schema and run-id derivation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract import (
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
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
        "execution_trace": [],
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
        execution_trace=[],
    )
    parsed = json.loads(b.model_dump_json())
    assert "created_at" not in parsed
    assert "toolchain" not in parsed


def test_plan_only_bundle_roundtrip_byte_identical() -> None:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    b = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=compute_plan_only_run_id(h, 1),
        resolved_seed=1,
        execution_trace=[
            RngTraceEntry(kind=ExecutionTraceKind.RNG, stream="ids", value="1"),
            AllocTraceEntry(kind=ExecutionTraceKind.ALLOC, stream="work_id", value="w1"),
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
        execution_trace=[],
        toolchain={"ffmpeg": "7.1", "ffprobe": "7.1", "platform": "darwin-arm64"},
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
