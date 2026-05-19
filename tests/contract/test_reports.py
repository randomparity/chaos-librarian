"""Tests for the four report schemas.

Reports are an adapter-facing contract; every field is part of the
public surface and must round-trip through Pydantic with no
serialization loss. ``extra="forbid"`` means typos in adapter-emitted
payloads are caught at the schema layer rather than silently ignored.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
    WORK_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.reports import (
    AssetHistoryEntry,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    VariantReport,
    WorkReport,
)


class TestAssetReport:
    """AssetReport carries initial/current snapshots + history.

    WHY: this is what adapter authors read to learn what happened to one
    asset across the timeline. Sprint 4 freezes the shape.
    """

    def _snapshot(self) -> AssetSnapshot:
        return AssetSnapshot(
            location_path="movies-hd/asset.mkv",
            version_id="version_0001",
            version_index=0,
        )

    def _history_entry(self) -> AssetHistoryEntry:
        return AssetHistoryEntry(
            logical_time_ns=2_000_000_000,
            event_id="move_001",
            action="move_asset",
            state_delta={"from": "movies-hd/asset.mkv", "to": "movies-hd/Blazar.mkv"},
        )

    def test_round_trip(self) -> None:
        report = AssetReport(
            schema_version=1,
            asset_id="asset_hd_main",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=self._snapshot(),
        )
        loaded = AssetReport.model_validate_json(report.model_dump_json())
        assert loaded == report

    def test_current_may_be_none(self) -> None:
        report = AssetReport(
            schema_version=1,
            asset_id="asset_hd_main",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=None,
        )
        parsed = json.loads(report.model_dump_json(exclude_none=False))
        assert parsed["current"] is None

    def test_rejects_extra_field(self) -> None:
        payload = {
            "schema_version": 1,
            "asset_id": "asset_hd_main",
            "initial": self._snapshot().model_dump(),
            "history": [],
            "current": None,
            "content_hash": "abc",  # Sprint 5 field — must be rejected at Sprint 4
        }
        with pytest.raises(ValidationError):
            AssetReport.model_validate(payload)

    def test_schema_version_constant_is_one(self) -> None:
        """The exported constant pins the Literal annotation."""
        assert ASSET_REPORT_SCHEMA_VERSION == 1


class TestOtherReports:
    """Work / variant / bundle reports list members + cross-references.

    WHY: the three reports are the navigation surface adapters use to
    walk from a work down to its assets, or from a bundle up to its
    variant.
    """

    def test_work_report_round_trip(self) -> None:
        wr = WorkReport(
            schema_version=1,
            work_id="work_blazar",
            title="Synthetic Blazar",
            variant_ids=["variant_hd"],
            asset_ids=["asset_hd_main"],
        )
        assert WorkReport.model_validate_json(wr.model_dump_json()) == wr

    def test_variant_report_round_trip(self) -> None:
        vr = VariantReport(
            schema_version=1,
            variant_id="variant_hd",
            work_id="work_blazar",
            label="hd",
            bundle_id="bundle_hd",
            asset_ids=["asset_hd_main"],
        )
        assert VariantReport.model_validate_json(vr.model_dump_json()) == vr

    def test_bundle_report_round_trip(self) -> None:
        br = BundleReport(
            schema_version=1,
            bundle_id="bundle_hd",
            variant_id="variant_hd",
            asset_ids=["asset_hd_main"],
            sidecar_ids=[],
        )
        assert BundleReport.model_validate_json(br.model_dump_json()) == br

    def test_constants_are_one(self) -> None:
        assert WORK_REPORT_SCHEMA_VERSION == 1
        assert VARIANT_REPORT_SCHEMA_VERSION == 1
        assert BUNDLE_REPORT_SCHEMA_VERSION == 1
