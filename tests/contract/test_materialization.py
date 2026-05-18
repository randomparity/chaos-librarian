"""Tests for the materialization report schema."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import MATERIALIZATION_SCHEMA_VERSION
from chaos_librarian.contract.materialization import (
    MaterializationReport,
    MaterializationStatus,
    ToolInvocation,
)


def test_success_report_roundtrip() -> None:
    r = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=uuid.uuid4(),
        status=MaterializationStatus.OK,
        toolchain={"ffmpeg": "7.1", "platform": "darwin-arm64"},
        invocations=[
            ToolInvocation(
                tool="ffmpeg",
                version="7.1",
                command=["ffmpeg", "-i", "in.mkv", "out.mp4"],
                exit_code=0,
                duration_ns=1_500_000_000,
            )
        ],
    )
    assert MaterializationReport.model_validate_json(r.model_dump_json()) == r


def test_failure_report_records_invocation() -> None:
    r = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=uuid.uuid4(),
        status=MaterializationStatus.TOOL_FAILED,
        toolchain={"ffmpeg": "7.1"},
        invocations=[
            ToolInvocation(
                tool="ffmpeg",
                version="7.1",
                command=["ffmpeg", "-i", "missing.mkv", "out.mp4"],
                exit_code=1,
                duration_ns=500_000_000,
            )
        ],
    )
    loaded = MaterializationReport.model_validate_json(r.model_dump_json())
    assert loaded.status is MaterializationStatus.TOOL_FAILED


def test_rejects_unknown_status() -> None:
    payload = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "status": "wat",
        "toolchain": {},
        "invocations": [],
    }
    with pytest.raises(ValidationError):
        MaterializationReport.model_validate(payload)
