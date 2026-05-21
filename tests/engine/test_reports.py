"""Tests for chaos_librarian.engine.reports.build_report_set."""

from __future__ import annotations

import uuid

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
)
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine.reports import ReportSet, build_report_set

_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _manifest_with_one_asset(*, location_path: str | None = "movies-hd/a.mkv") -> Manifest:
    locations = (
        [
            ManifestLocation(
                id="location_0001",
                asset_id="asset_hd_main",
                path=location_path,
            )
        ]
        if location_path is not None
        else []
    )
    return Manifest(
        schema_version=4,
        works=[ManifestWork(id="work_blazar", title="Synthetic Blazar")],
        variants=[ManifestVariant(id="variant_hd", work_id="work_blazar", label="hd")],
        bundles=[ManifestBundle(id="bundle_hd", variant_id="variant_hd")],
        assets=[
            ManifestAsset(
                id="asset_hd_main",
                bundle_id="bundle_hd",
                role="primary_video",
                container="mkv",
                duration_seconds=12.0,
            )
        ],
        versions=[ManifestVersion(id="version_0001", asset_id="asset_hd_main", index=0)],
        locations=locations,
        sidecars=[],
    )


def _atomic_entry(
    *,
    event_id: str,
    action: str,
    target: str,
    delta: dict[str, object],
    input_version_ids: list[str] | None = None,
    output_version_ids: list[str] | None = None,
) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id=event_id,
        scenario_id="t",
        run_id=_RUN_ID,
        logical_time_ns=1_000_000_000,
        action=action,
        target_ids=[target],
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        state_delta=delta,
        phase=JournalPhase.ATOMIC,
    )


class TestBuildReportSet:
    """Reports describe the asset/work/variant/bundle cross-cuts of a run.

    WHY: this is the adapter-facing contract; every cross-cut listed in
    the design must populate.
    """

    def test_empty_journal_yields_initial_history(self) -> None:
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        assert isinstance(rs, ReportSet)
        assert len(rs.assets) == 1
        assert rs.assets[0].history == []
        assert rs.assets[0].current == rs.assets[0].initial

    def test_history_filters_to_asset_target(self) -> None:
        m = _manifest_with_one_asset()
        entry = _atomic_entry(
            event_id="move_001",
            action="move_asset",
            target="asset_hd_main",
            delta={"to": "movies-hd/Blazar.mkv"},
        )
        non_matching = _atomic_entry(
            event_id="move_002",
            action="move_asset",
            target="asset_other",
            delta={"to": "movies-hd/Other.mkv"},
        )
        rs = build_report_set(initial=m, current=m, journal=[entry, non_matching])
        asset_report = rs.assets[0]
        assert len(asset_report.history) == 1
        assert asset_report.history[0].event_id == "move_001"
        assert asset_report.history[0].action == "move_asset"
        assert asset_report.history[0].state_delta == {"to": "movies-hd/Blazar.mkv"}

    def test_deleted_asset_has_none_current(self) -> None:
        initial = _manifest_with_one_asset()
        current = _manifest_with_one_asset(location_path=None)
        # In a real run the current manifest would also drop the location row;
        # here the snapshot lookup falls back to "no location" → current is None.
        entry = _atomic_entry(
            event_id="del_001",
            action="delete_file",
            target="asset_hd_main",
            delta={},
        )
        rs = build_report_set(initial=initial, current=current, journal=[entry])
        assert rs.assets[0].current is None
        assert any(h.action == "delete_file" for h in rs.assets[0].history)

    def test_work_lists_variants_and_transitive_assets(self) -> None:
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        wr = rs.works[0]
        assert wr.work_id == "work_blazar"
        assert wr.variant_ids == ["variant_hd"]
        assert wr.asset_ids == ["asset_hd_main"]

    def test_variant_links_bundle_and_work(self) -> None:
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        vr = rs.variants[0]
        assert vr.variant_id == "variant_hd"
        assert vr.work_id == "work_blazar"
        assert vr.bundle_id == "bundle_hd"
        assert vr.asset_ids == ["asset_hd_main"]

    def test_bundle_lists_assets_and_sidecars(self) -> None:
        m = _manifest_with_one_asset()
        m.sidecars.append(
            ManifestSidecar(
                id="sidecar_0001",
                asset_id="asset_hd_main",
                kind="subtitles",
                path="movies-hd/a.eng.srt",
                language="eng",
            )
        )
        rs = build_report_set(initial=m, current=m, journal=[])
        br = rs.bundles[0]
        assert br.bundle_id == "bundle_hd"
        assert br.asset_ids == ["asset_hd_main"]
        assert br.sidecar_ids == ["sidecar_0001"]

    def test_path_history_empty_for_static_scenario(self) -> None:
        """WHY: AssetReport.path_history must default to [] when no filesystem events ran.

        Sprint 6 added the field; reports for static scenarios must not
        invent path_history rows that didn't happen.
        """
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        assert rs.assets[0].path_history == []

    def test_path_history_populated_for_move_asset(self) -> None:
        """WHY: a filesystem-affecting journal event must surface in path_history.

        Drift-locks AssetReport's Sprint 6 wiring against a future refactor
        that forgets to call ``derive_path_history``.
        """
        m = _manifest_with_one_asset()
        entry = _atomic_entry(
            event_id="move_001",
            action="move_asset",
            target="asset_hd_main",
            delta={
                "from_path": "movies-hd/a.mkv",
                "to_path": "movies-hd/Blazar.mkv",
            },
        )
        rs = build_report_set(initial=m, current=m, journal=[entry])
        path_history = rs.assets[0].path_history
        assert len(path_history) == 1
        assert path_history[0].event_id == "move_001"
        assert path_history[0].from_path == "movies-hd/a.mkv"
        assert path_history[0].to_path == "movies-hd/Blazar.mkv"

    def test_version_history_empty_for_static_scenario(self) -> None:
        """WHY: AssetReport.version_history must default to [] when no version events ran.

        Sprint 7 added the field; reports for static scenarios must not
        invent version_history rows that didn't happen.
        """
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        assert rs.assets[0].version_history == []

    def test_version_history_populated_for_reencode_video(self) -> None:
        """WHY: a version-affecting journal event must surface in version_history.

        Drift-locks AssetReport's Sprint 7 wiring against a future refactor
        that forgets to call ``derive_version_history``.
        """
        m = _manifest_with_one_asset()
        entry = _atomic_entry(
            event_id="reencode_001",
            action="reencode_video",
            target="asset_hd_main",
            input_version_ids=["version_0001"],
            output_version_ids=["version_0002"],
            delta={
                "resolution": "sd",
                "codec": "h264",
                "input_path": "movies-hd/a.mkv",
                "output_path": "movies-hd/a.mkv",
            },
        )
        rs = build_report_set(initial=m, current=m, journal=[entry])
        version_history = rs.assets[0].version_history
        assert len(version_history) == 1
        assert version_history[0].event_id == "reencode_001"
        assert version_history[0].action == TimelineActionName.REENCODE_VIDEO
        assert version_history[0].input_version_id == "version_0001"
        assert version_history[0].output_version_id == "version_0002"
        assert version_history[0].state_delta_summary == {
            "resolution": "sd",
            "codec": "h264",
        }

    def test_iteration_order_is_stable(self) -> None:
        """Reports sort by id lexicographically.

        WHY: report files are written one per id; bit-identical fixtures
        require deterministic enumeration.
        """
        m = _manifest_with_one_asset()
        rs1 = build_report_set(initial=m, current=m, journal=[])
        rs2 = build_report_set(initial=m, current=m, journal=[])
        assert [a.asset_id for a in rs1.assets] == [a.asset_id for a in rs2.assets]
