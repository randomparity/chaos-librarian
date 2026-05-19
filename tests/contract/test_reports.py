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
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream
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
            schema_version=2,
            asset_id="asset_hd_main",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=self._snapshot(),
        )
        loaded = AssetReport.model_validate_json(report.model_dump_json())
        assert loaded == report

    def test_current_may_be_none(self) -> None:
        report = AssetReport(
            schema_version=2,
            asset_id="asset_hd_main",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=None,
        )
        parsed = json.loads(report.model_dump_json(exclude_none=False))
        assert parsed["current"] is None

    def test_rejects_extra_field(self) -> None:
        payload = {
            "schema_version": 2,
            "asset_id": "asset_hd_main",
            "initial": self._snapshot().model_dump(),
            "history": [],
            "current": None,
            "not_a_real_field": "abc",  # extra="forbid" rejects unknown keys
        }
        with pytest.raises(ValidationError):
            AssetReport.model_validate(payload)

    def test_schema_version_constant_is_two(self) -> None:
        """The exported constant pins the Literal annotation."""
        assert ASSET_REPORT_SCHEMA_VERSION == 2


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


def test_asset_snapshot_carries_content_hash_and_probed():
    """WHY: adapter consumers see materialized facts on AssetReport without
    joining back through manifest.versions[]; if the fields aren't carried,
    consumers re-implement the join and drift apart."""
    snap = AssetSnapshot(
        location_path="library/movie/main.mkv",
        version_id="v0",
        version_index=0,
        content_hash="sha256:" + "0" * 64,
        probed=ProbedMedia(
            container="matroska,webm",
            duration_seconds=2.0,
            size_bytes=12345,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        ),
    )
    blob = snap.model_dump_json(exclude_none=True)
    loaded = AssetSnapshot.model_validate_json(blob)
    assert loaded == snap


def test_asset_snapshot_omits_new_fields_when_none():
    """WHY: plan-only reports stay byte-stable post-bump; the writer's
    exclude_none=True relies on the defaults being None."""
    snap = AssetSnapshot(location_path=None, version_id="v0", version_index=0)
    rendered = snap.model_dump(exclude_none=True)
    assert "content_hash" not in rendered
    assert "probed" not in rendered


def test_asset_report_schema_version_is_two():
    assert ASSET_REPORT_SCHEMA_VERSION == 2


def test_other_report_schema_versions_stay_at_one():
    """WHY: only AssetReport bumps; Work/Variant/Bundle carry id lists, not
    embedded snapshots. If one of them silently bumps to 2, voom-v2 will
    fail at the discriminator."""
    assert WORK_REPORT_SCHEMA_VERSION == 1
    assert VARIANT_REPORT_SCHEMA_VERSION == 1
    assert BUNDLE_REPORT_SCHEMA_VERSION == 1
