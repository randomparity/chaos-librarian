"""Tests for the run-directory sentinel schema."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.run_sentinel import RunSentinel


def test_materialize_sentinel_roundtrip() -> None:
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian 0.0.0",
        created_at=datetime(2026, 5, 17, 12, 0, tzinfo=UTC),
    )
    blob = sentinel.model_dump_json()
    loaded = RunSentinel.model_validate_json(blob)
    assert loaded == sentinel


def test_plan_only_sentinel_omits_created_at() -> None:
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian 0.0.0",
    )
    blob = sentinel.model_dump_json(exclude_none=True)
    parsed = json.loads(blob)
    assert "created_at" not in parsed


def test_plan_only_sentinel_roundtrip_without_created_at() -> None:
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian 0.0.0",
    )
    blob = sentinel.model_dump_json(exclude_none=True)
    loaded = RunSentinel.model_validate_json(blob)
    assert loaded.created_at is None


def test_rejects_missing_run_id() -> None:
    with pytest.raises(ValidationError):
        RunSentinel(
            schema_version=RUN_SENTINEL_SCHEMA_VERSION,
            created_by="chaos-librarian 0.0.0",
        )  # type: ignore[call-arg]  # ty:ignore[missing-argument]


def test_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError):
        RunSentinel(
            run_id=uuid.uuid4(),
            schema_version=999,
            created_by="chaos-librarian 0.0.0",
        )


def test_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RunSentinel(
            run_id=uuid.uuid4(),
            schema_version=RUN_SENTINEL_SCHEMA_VERSION,
            created_by="chaos-librarian 0.0.0",
            bogus="x",  # type: ignore[call-arg]  # ty:ignore[unknown-argument]
        )
