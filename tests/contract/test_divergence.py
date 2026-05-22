"""Tests for the Sprint 9 divergence report contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract.divergence import DivergenceReport


def _metadata() -> tuple[dict[str, object], dict[str, object]]:
    fixture: dict[str, object] = {
        "run_dir": "/tmp/chaos-run",
        "execution_mode": "plan_only",
        "asset_count": 1,
        "journal_entries": 2,
    }
    observed: dict[str, object] = {
        "consumer_name": "voom-v2",
        "consumer_version": "0.9.0",
        "observed_at": "2026-05-22T12:00:00Z",
        "asset_count": 1,
    }
    return fixture, observed


def _report_payload(*, ok: bool, findings: list[dict[str, object]]) -> dict[str, object]:
    fixture, observed = _metadata()
    return {
        "schema_version": 1,
        "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
        "mode": "final-state",
        "ok": ok,
        "fixture": fixture,
        "observed": observed,
        "findings": findings,
    }


def test_divergence_report_round_trips_final_state_finding() -> None:
    payload = _report_payload(
        ok=False,
        findings=[
            {
                "code": "D_PATH_MISMATCH",
                "severity": "error",
                "message": "Path differs for asset_hd_main.",
                "oracle_asset_id": "asset_hd_main",
                "observed_ref": "obs-asset-1",
                "expected": {"current_path": "movies/Expected.mkv"},
                "observed": {"current_path": "movies/Actual.mkv"},
                "evidence": [
                    {
                        "kind": "content_hash",
                        "value": "sha256:" + "a" * 64,
                        "oracle_asset_id": "asset_hd_main",
                        "observed_ref": "obs-asset-1",
                    }
                ],
            }
        ],
    )

    report = DivergenceReport.model_validate(payload)

    finding = report.findings[0]
    assert finding.code == "D_PATH_MISMATCH"
    assert finding.expected == {"current_path": "movies/Expected.mkv"}
    assert finding.observed == {"current_path": "movies/Actual.mkv"}
    assert finding.evidence[0].kind == "content_hash"


def test_divergence_report_round_trips_identity_history_related_events() -> None:
    payload = _report_payload(
        ok=False,
        findings=[
            {
                "code": "D_IDENTITY_SPLIT",
                "severity": "error",
                "message": "Observed lifecycle split.",
                "oracle_asset_id": "asset_hd_main",
                "oracle_event_id": "ev_delete_001",
                "related_oracle_event_ids": ["ev_add_002"],
                "observed_ref": "obs-asset-before",
                "observed": {
                    "before_observed_ref": "obs-asset-before",
                    "after_observed_ref": "obs-asset-after",
                },
            }
        ],
    )
    payload["mode"] = "identity-history"

    report = DivergenceReport.model_validate(payload)

    assert report.findings[0].related_oracle_event_ids == ["ev_add_002"]
    assert report.mode == "identity-history"


def test_divergence_report_metadata_round_trips() -> None:
    payload = _report_payload(ok=True, findings=[])

    report = DivergenceReport.model_validate(payload)

    assert report.fixture.run_dir == "/tmp/chaos-run"
    assert report.observed.consumer_name == "voom-v2"
    assert report.observed.consumer_version == "0.9.0"


def test_divergence_report_rejects_ok_true_with_error_finding() -> None:
    payload = _report_payload(
        ok=True,
        findings=[
            {
                "code": "D_ASSET_MISSING",
                "severity": "error",
                "message": "Missing asset.",
                "oracle_asset_id": "asset_hd_main",
            }
        ],
    )

    with pytest.raises(ValidationError):
        DivergenceReport.model_validate(payload)


def test_divergence_report_rejects_ok_false_without_error_findings() -> None:
    payload = _report_payload(ok=False, findings=[])

    with pytest.raises(ValidationError):
        DivergenceReport.model_validate(payload)
