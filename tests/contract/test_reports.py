"""Tests for the hierarchy report schemas.

Reports are an adapter-facing contract; every field is part of the
public surface and must round-trip through Pydantic with no
serialization loss. ``extra="forbid"`` means typos in adapter-emitted
payloads are caught at the schema layer rather than silently ignored.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import chaos_librarian.contract.reports as reports_module
from chaos_librarian.contract import (
    ALBUM_REPORT_SCHEMA_VERSION,
    ARTIST_REPORT_SCHEMA_VERSION,
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    DISC_REPORT_SCHEMA_VERSION,
    EPISODE_REPORT_SCHEMA_VERSION,
    MOVIE_REPORT_SCHEMA_VERSION,
    SEASON_REPORT_SCHEMA_VERSION,
    SERIES_REPORT_SCHEMA_VERSION,
    TRACK_REPORT_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.profiles import CorruptionRecord, ProfileName
from chaos_librarian.contract.reports import (
    AlbumReport,
    ArtistReport,
    AssetHistoryEntry,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    DiscReport,
    EpisodeReport,
    MovieReport,
    PathHistoryEntry,
    SeasonReport,
    SeriesReport,
    TrackReport,
    VariantReport,
    VersionHistoryEntry,
)
from chaos_librarian.contract.scenario import TimelineActionName


def _corruption_record() -> CorruptionRecord:
    return CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id="corrupt_header_001",
        corruptor="container_header_v1",
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:42:corrupt_header_001:asset_main",
    )


def _asset_report_topology_payload() -> dict[str, object]:
    return {
        "parent_kind": "episode",
        "parent_id": "episode_01",
        "movie_id": None,
        "series_id": "series_starline",
        "season_id": "season_01",
        "episode_id": "episode_01",
        "artist_id": None,
        "album_id": None,
        "disc_id": None,
        "track_id": None,
        "variant_id": "variant_episode",
        "bundle_id": "bundle_episode",
    }


class TestAssetReport:
    """AssetReport carries initial/current snapshots + history.

    WHY: this is what adapter authors read to learn what happened to one
    asset across the timeline and how it sits in the media hierarchy.
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

    def _report(self, current: AssetSnapshot | None) -> AssetReport:
        return AssetReport(
            schema_version=9,
            asset_id="asset_hd_main",
            parent_kind=ParentKind.MOVIE,
            parent_id="movie_blazar",
            movie_id="movie_blazar",
            series_id=None,
            season_id=None,
            episode_id=None,
            artist_id=None,
            album_id=None,
            disc_id=None,
            track_id=None,
            variant_id="variant_hd",
            bundle_id="bundle_hd",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=current,
        )

    def test_round_trip(self) -> None:
        report = self._report(current=self._snapshot())
        loaded = AssetReport.model_validate_json(report.model_dump_json())
        assert loaded == report

    def test_current_may_be_none(self) -> None:
        report = self._report(current=None)
        parsed = json.loads(report.model_dump_json(exclude_none=False))
        assert parsed["current"] is None

    def test_rejects_extra_field(self) -> None:
        payload = {
            "schema_version": 9,
            "asset_id": "asset_hd_main",
            "parent_kind": "movie",
            "parent_id": "movie_blazar",
            "movie_id": "movie_blazar",
            "series_id": None,
            "season_id": None,
            "episode_id": None,
            "artist_id": None,
            "album_id": None,
            "disc_id": None,
            "track_id": None,
            "variant_id": "variant_hd",
            "bundle_id": "bundle_hd",
            "initial": self._snapshot().model_dump(),
            "history": [],
            "current": None,
            "not_a_real_field": "abc",  # extra="forbid" rejects unknown keys
        }
        with pytest.raises(ValidationError):
            AssetReport.model_validate(payload)

    def test_schema_version_constant_is_nine(self) -> None:
        """The exported constant pins the Literal annotation."""
        assert ASSET_REPORT_SCHEMA_VERSION == 9


class TestOtherReports:
    """Domain, variant, and bundle reports list members + cross-references.

    WHY: these reports are the navigation surface adapters use to walk
    from hierarchy entities down to assets, or from a bundle up to its
    variant.
    """

    def test_domain_reports_round_trip(self) -> None:
        reports = [
            MovieReport(
                schema_version=1,
                movie_id="movie_orbit",
                title="Orbit",
                variant_ids=["variant_movie"],
                asset_ids=["asset_movie"],
            ),
            SeriesReport(
                schema_version=1,
                series_id="series_starline",
                title="Starline",
                season_ids=["season_01"],
                episode_ids=["episode_01"],
                asset_ids=["asset_episode"],
            ),
            SeasonReport(
                schema_version=1,
                season_id="season_01",
                series_id="series_starline",
                season_number=1,
                title="Season 1",
                episode_ids=["episode_01"],
                asset_ids=["asset_episode"],
            ),
            EpisodeReport(
                schema_version=1,
                episode_id="episode_01",
                season_id="season_01",
                episode_number=1,
                title="Pilot",
                aired_on=None,
                absolute_number=None,
                variant_ids=["variant_episode"],
                asset_ids=["asset_episode"],
            ),
            ArtistReport(
                schema_version=1,
                artist_id="artist_north",
                name="North Index",
                album_ids=["album_winter"],
                track_ids=["track_opening"],
                asset_ids=["asset_track"],
            ),
            AlbumReport(
                schema_version=1,
                album_id="album_winter",
                artist_id="artist_north",
                title="Winter Index",
                release_year=2024,
                disc_ids=["disc_01"],
                track_ids=["track_opening"],
                asset_ids=["asset_track"],
            ),
            DiscReport(
                schema_version=1,
                disc_id="disc_01",
                album_id="album_winter",
                disc_number=1,
                track_ids=["track_opening"],
                asset_ids=["asset_track"],
            ),
            TrackReport(
                schema_version=1,
                track_id="track_opening",
                disc_id="disc_01",
                track_number=1,
                title="Opening",
                performers=["North Index"],
                variant_ids=["variant_track"],
                asset_ids=["asset_track"],
            ),
        ]

        for report in reports:
            assert type(report).model_validate_json(report.model_dump_json()) == report

    def test_variant_report_round_trip(self) -> None:
        vr = VariantReport(
            schema_version=2,
            variant_id="variant_hd",
            parent_kind=ParentKind.MOVIE,
            parent_id="movie_blazar",
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

    def test_constants_match_report_contract(self) -> None:
        assert MOVIE_REPORT_SCHEMA_VERSION == 1
        assert SERIES_REPORT_SCHEMA_VERSION == 1
        assert SEASON_REPORT_SCHEMA_VERSION == 1
        assert EPISODE_REPORT_SCHEMA_VERSION == 1
        assert ARTIST_REPORT_SCHEMA_VERSION == 1
        assert ALBUM_REPORT_SCHEMA_VERSION == 1
        assert DISC_REPORT_SCHEMA_VERSION == 1
        assert TRACK_REPORT_SCHEMA_VERSION == 1
        assert BUNDLE_REPORT_SCHEMA_VERSION == 1
        assert VARIANT_REPORT_SCHEMA_VERSION == 2


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
            streams=[
                ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480, fps=24.0)
            ],
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


def test_asset_snapshot_round_trips_corruption_metadata() -> None:
    snap = AssetSnapshot(
        location_path="movies-hd/asset.mkv",
        version_id="version_0002",
        version_index=1,
        corruption=_corruption_record(),
    )

    loaded = AssetSnapshot.model_validate_json(snap.model_dump_json())

    assert loaded == snap
    assert loaded.corruption is not None
    assert loaded.corruption.event_id == "corrupt_header_001"


def test_asset_report_schema_version_is_eight() -> None:
    assert ASSET_REPORT_SCHEMA_VERSION == 9


def test_domain_report_constants_start_at_one() -> None:
    assert MOVIE_REPORT_SCHEMA_VERSION == 1
    assert SERIES_REPORT_SCHEMA_VERSION == 1
    assert SEASON_REPORT_SCHEMA_VERSION == 1
    assert EPISODE_REPORT_SCHEMA_VERSION == 1
    assert ARTIST_REPORT_SCHEMA_VERSION == 1
    assert ALBUM_REPORT_SCHEMA_VERSION == 1
    assert DISC_REPORT_SCHEMA_VERSION == 1
    assert TRACK_REPORT_SCHEMA_VERSION == 1
    assert VARIANT_REPORT_SCHEMA_VERSION == 2
    assert ASSET_REPORT_SCHEMA_VERSION == 9
    assert BUNDLE_REPORT_SCHEMA_VERSION == 1


def test_variant_report_uses_parent_kind_and_parent_id() -> None:
    report = VariantReport(
        schema_version=2,
        variant_id="variant_movie",
        parent_kind=ParentKind.MOVIE,
        parent_id="movie_orbit",
        label="1080p",
        bundle_id="bundle_movie",
        asset_ids=["asset_movie"],
    )

    assert VariantReport.model_validate_json(report.model_dump_json()) == report


def test_asset_report_v9_carries_topology_fields() -> None:
    snapshot = AssetSnapshot(location_path=None, version_id="version_0001", version_index=0)
    report = AssetReport(
        schema_version=9,
        asset_id="asset_episode",
        parent_kind=ParentKind.EPISODE,
        parent_id="episode_01",
        movie_id=None,
        series_id="series_starline",
        season_id="season_01",
        episode_id="episode_01",
        artist_id=None,
        album_id=None,
        disc_id=None,
        track_id=None,
        variant_id="variant_episode",
        bundle_id="bundle_episode",
        initial=snapshot,
        current=snapshot,
    )

    assert AssetReport.model_validate_json(report.model_dump_json()) == report


def test_work_report_is_removed() -> None:
    assert not hasattr(reports_module, "WorkReport")


def test_path_history_entry_round_trip() -> None:
    payload = {
        "event_id": "ev_move_001",
        "action": "move_asset",
        "logical_time_ns": 1_000_000_000,
        "from_path": "movies-hd/old.mkv",
        "to_path": "movies-hd/new.mkv",
        "temp_path": None,
    }
    entry = PathHistoryEntry.model_validate(payload)
    assert entry.from_path == "movies-hd/old.mkv"
    assert entry.to_path == "movies-hd/new.mkv"
    assert entry.temp_path is None
    assert entry.action == TimelineActionName.MOVE_ASSET


def test_asset_report_path_history_defaults_to_empty_list() -> None:
    payload = {
        "schema_version": 9,
        "asset_id": "asset_hd_main",
        **_asset_report_topology_payload(),
        "initial": {
            "location_path": "movies-hd/asset_hd_main.mkv",
            "version_id": "version_0001",
            "version_index": 0,
        },
        "history": [],
        "current": {
            "location_path": "movies-hd/asset_hd_main.mkv",
            "version_id": "version_0001",
            "version_index": 0,
        },
    }
    report = AssetReport.model_validate(payload)
    assert report.path_history == []


def test_asset_report_v9_round_trip_with_path_history() -> None:
    payload = {
        "schema_version": 9,
        "asset_id": "asset_hd_main",
        **_asset_report_topology_payload(),
        "initial": {
            "location_path": "movies-hd/asset_hd_main.mkv",
            "version_id": "version_0001",
            "version_index": 0,
        },
        "history": [],
        "current": None,
        "path_history": [
            {
                "event_id": "ev_delete_001",
                "action": "delete_file",
                "logical_time_ns": 1_000_000_000,
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": None,
                "temp_path": None,
            }
        ],
    }
    report = AssetReport.model_validate(payload)
    assert len(report.path_history) == 1
    assert report.path_history[0].action == TimelineActionName.DELETE_FILE


def test_version_history_entry_round_trip():
    entry = VersionHistoryEntry(
        event_id="ev_rv_001",
        action=TimelineActionName.REENCODE_VIDEO,
        logical_time_ns=3_000_000_000,
        input_version_id="version_0001",
        output_version_id="version_0002",
        state_delta_summary={"resolution": "sd", "codec": "h264"},
    )
    assert entry.action == TimelineActionName.REENCODE_VIDEO
    assert entry.state_delta_summary == {"resolution": "sd", "codec": "h264"}


def test_version_history_entry_extract_no_versions():
    entry = VersionHistoryEntry(
        event_id="ev_xs_001",
        action=TimelineActionName.EXTRACT_SUBTITLE,
        logical_time_ns=4_000_000_000,
        input_version_id=None,
        output_version_id=None,
        state_delta_summary={},
    )
    assert entry.input_version_id is None
    assert entry.output_version_id is None


def test_asset_report_v9_default_version_history_empty():
    snapshot = AssetSnapshot(
        location_path="movies/x.mkv",
        version_id="v0",
        version_index=0,
    )
    report = AssetReport(
        schema_version=9,
        asset_id="asset_main",
        parent_kind=ParentKind.TRACK,
        parent_id="track_main",
        movie_id=None,
        series_id=None,
        season_id=None,
        episode_id=None,
        artist_id="artist_main",
        album_id="album_main",
        disc_id="disc_main",
        track_id="track_main",
        variant_id="variant_main",
        bundle_id="bundle_main",
        initial=snapshot,
        current=snapshot,
    )
    assert report.version_history == []
    assert report.schema_version == 9
