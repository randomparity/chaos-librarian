"""Tests for chaos_librarian.engine.reports.build_report_set."""

from __future__ import annotations

import uuid

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAlbum,
    ManifestArtist,
    ManifestAsset,
    ManifestBundle,
    ManifestDisc,
    ManifestEpisode,
    ManifestLocation,
    ManifestMovie,
    ManifestSeason,
    ManifestSeries,
    ManifestSidecar,
    ManifestTrack,
    ManifestVariant,
    ManifestVersion,
    ProbedMedia,
    ProbedStream,
    StreamKind,
)
from chaos_librarian.contract.profiles import CorruptionRecord, ProfileName
from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
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
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="movie_blazar", title="Synthetic Blazar", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="variant_hd",
                parent_kind=ParentKind.MOVIE,
                parent_id="movie_blazar",
                label="hd",
            )
        ],
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


def _manifest_with_domain_hierarchy() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="movie_orbit", title="Orbit", layout="movie_flat")],
        series=[
            ManifestSeries(
                id="series_starline",
                title="Starline",
                layout="season_folders",
                episode_naming="sxxexx_title",
            )
        ],
        seasons=[
            ManifestSeason(
                id="season_specials",
                series_id="series_starline",
                season_number=0,
                title="Specials",
            )
        ],
        episodes=[
            ManifestEpisode(
                id="episode_signal",
                season_id="season_specials",
                episode_number=1,
                title="First Signal",
                absolute_number=7,
            )
        ],
        artists=[
            ManifestArtist(
                id="artist_north",
                name="North Index",
                layout="artist_album_disc",
                track_naming="track_number_title",
            )
        ],
        albums=[
            ManifestAlbum(
                id="album_winter",
                artist_id="artist_north",
                title="Winter Index",
                release_year=2024,
            )
        ],
        discs=[ManifestDisc(id="disc_winter_01", album_id="album_winter", disc_number=1)],
        tracks=[
            ManifestTrack(
                id="track_opening",
                disc_id="disc_winter_01",
                track_number=1,
                title="Opening",
                performers=["North Index"],
            )
        ],
        variants=[
            ManifestVariant(
                id="variant_movie",
                parent_kind=ParentKind.MOVIE,
                parent_id="movie_orbit",
                label="1080p",
            ),
            ManifestVariant(
                id="variant_episode",
                parent_kind=ParentKind.EPISODE,
                parent_id="episode_signal",
                label="1080p",
            ),
            ManifestVariant(
                id="variant_track",
                parent_kind=ParentKind.TRACK,
                parent_id="track_opening",
                label="lossless",
            ),
        ],
        bundles=[
            ManifestBundle(id="bundle_movie", variant_id="variant_movie"),
            ManifestBundle(id="bundle_episode", variant_id="variant_episode"),
            ManifestBundle(id="bundle_track", variant_id="variant_track"),
        ],
        assets=[
            ManifestAsset(
                id="asset_movie",
                bundle_id="bundle_movie",
                role="primary_video",
                container="mkv",
                duration_seconds=12.0,
            ),
            ManifestAsset(
                id="asset_episode",
                bundle_id="bundle_episode",
                role="primary_video",
                container="mkv",
                duration_seconds=12.0,
            ),
            ManifestAsset(
                id="asset_track",
                bundle_id="bundle_track",
                role="main",
                container="flac",
                duration_seconds=180.0,
            ),
        ],
        versions=[
            ManifestVersion(id="version_movie", asset_id="asset_movie", index=0),
            ManifestVersion(id="version_episode", asset_id="asset_episode", index=0),
            ManifestVersion(id="version_track", asset_id="asset_track", index=0),
        ],
        locations=[
            ManifestLocation(
                id="location_movie",
                asset_id="asset_movie",
                path="library/Orbit - 1080p.mkv",
            ),
            ManifestLocation(
                id="location_episode",
                asset_id="asset_episode",
                path="library/Starline/S00E01.mkv",
            ),
            ManifestLocation(
                id="location_track",
                asset_id="asset_track",
                path="library/North Index/Opening.flac",
            ),
        ],
        sidecars=[],
    )


def _corruption_record() -> CorruptionRecord:
    return CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id="corrupt_header_001",
        corruptor="container_header_v1",
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:42:corrupt_header_001:asset_hd_main",
    )


def _probed_media() -> ProbedMedia:
    return ProbedMedia(
        container="matroska,webm",
        duration_seconds=1.0,
        size_bytes=12345,
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
    )


def _manifest_with_two_versions() -> Manifest:
    manifest = _manifest_with_one_asset()
    manifest.versions = [
        ManifestVersion(id="version_0001", asset_id="asset_hd_main", index=0),
        ManifestVersion(
            id="version_0002",
            asset_id="asset_hd_main",
            index=1,
            content_hash="sha256:" + "1" * 64,
            probed=_probed_media(),
            corruption=_corruption_record(),
        ),
    ]
    return manifest


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
    """Reports describe the asset/domain/variant/bundle cross-cuts of a run.

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

    def test_asset_report_includes_initial_topology(self) -> None:
        m = _manifest_with_one_asset()

        rs = build_report_set(initial=m, current=m, journal=[])
        asset_report = rs.assets[0]

        assert asset_report.asset_id == "asset_hd_main"
        assert asset_report.parent_kind is ParentKind.MOVIE
        assert asset_report.parent_id == "movie_blazar"
        assert asset_report.movie_id == "movie_blazar"
        assert asset_report.series_id is None
        assert asset_report.variant_id == "variant_hd"
        assert asset_report.bundle_id == "bundle_hd"

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
        entry = _atomic_entry(
            event_id="del_001",
            action="delete_file",
            target="asset_hd_main",
            delta={},
        )

        rs = build_report_set(initial=initial, current=current, journal=[entry])

        assert rs.assets[0].current is None
        assert any(h.action == "delete_file" for h in rs.assets[0].history)

    def test_movie_lists_variants_and_transitive_assets(self) -> None:
        m = _manifest_with_one_asset()

        rs = build_report_set(initial=m, current=m, journal=[])
        report = rs.movies[0]

        assert report.movie_id == "movie_blazar"
        assert report.variant_ids == ["variant_hd"]
        assert report.asset_ids == ["asset_hd_main"]

    def test_series_season_and_episode_reports_use_transitive_asset_ids(self) -> None:
        m = _manifest_with_domain_hierarchy()

        rs = build_report_set(initial=m, current=m, journal=[])

        assert rs.series[0].series_id == "series_starline"
        assert rs.series[0].season_ids == ["season_specials"]
        assert rs.series[0].episode_ids == ["episode_signal"]
        assert rs.series[0].asset_ids == ["asset_episode"]
        assert rs.seasons[0].season_id == "season_specials"
        assert rs.seasons[0].episode_ids == ["episode_signal"]
        assert rs.seasons[0].asset_ids == ["asset_episode"]
        assert rs.episodes[0].episode_id == "episode_signal"
        assert rs.episodes[0].variant_ids == ["variant_episode"]
        assert rs.episodes[0].asset_ids == ["asset_episode"]

    def test_episode_move_reports_current_season_topology(self) -> None:
        """WHY: hierarchy timeline moves must update report topology, not just manifest."""
        initial = _manifest_with_domain_hierarchy()
        current = _manifest_with_domain_hierarchy()
        current.seasons.append(
            ManifestSeason(
                id="season_two",
                series_id="series_starline",
                season_number=2,
                title="Second",
            )
        )
        current.episodes[0] = current.episodes[0].model_copy(update={"season_id": "season_two"})

        rs = build_report_set(initial=initial, current=current, journal=[])

        assets = {report.asset_id: report for report in rs.assets}
        seasons = {report.season_id: report for report in rs.seasons}
        assert assets["asset_episode"].season_id == "season_two"
        assert rs.episodes[0].season_id == "season_two"
        assert seasons["season_specials"].episode_ids == []
        assert seasons["season_specials"].asset_ids == []
        assert seasons["season_two"].episode_ids == ["episode_signal"]
        assert seasons["season_two"].asset_ids == ["asset_episode"]

    def test_artist_album_disc_and_track_reports_use_transitive_asset_ids(self) -> None:
        m = _manifest_with_domain_hierarchy()

        rs = build_report_set(initial=m, current=m, journal=[])

        assert rs.artists[0].artist_id == "artist_north"
        assert rs.artists[0].album_ids == ["album_winter"]
        assert rs.artists[0].track_ids == ["track_opening"]
        assert rs.artists[0].asset_ids == ["asset_track"]
        assert rs.albums[0].album_id == "album_winter"
        assert rs.albums[0].disc_ids == ["disc_winter_01"]
        assert rs.albums[0].track_ids == ["track_opening"]
        assert rs.albums[0].asset_ids == ["asset_track"]
        assert rs.discs[0].disc_id == "disc_winter_01"
        assert rs.discs[0].track_ids == ["track_opening"]
        assert rs.discs[0].asset_ids == ["asset_track"]
        assert rs.tracks[0].track_id == "track_opening"
        assert rs.tracks[0].variant_ids == ["variant_track"]
        assert rs.tracks[0].asset_ids == ["asset_track"]

    def test_track_move_reports_current_disc_topology(self) -> None:
        """WHY: music hierarchy moves must update report topology, not just manifest."""
        initial = _manifest_with_domain_hierarchy()
        current = _manifest_with_domain_hierarchy()
        current.discs.append(
            ManifestDisc(id="disc_winter_02", album_id="album_winter", disc_number=2)
        )
        current.tracks[0] = current.tracks[0].model_copy(update={"disc_id": "disc_winter_02"})

        rs = build_report_set(initial=initial, current=current, journal=[])

        assets = {report.asset_id: report for report in rs.assets}
        discs = {report.disc_id: report for report in rs.discs}
        assert assets["asset_track"].disc_id == "disc_winter_02"
        assert rs.tracks[0].disc_id == "disc_winter_02"
        assert discs["disc_winter_01"].track_ids == []
        assert discs["disc_winter_01"].asset_ids == []
        assert discs["disc_winter_02"].track_ids == ["track_opening"]
        assert discs["disc_winter_02"].asset_ids == ["asset_track"]

    def test_variant_links_bundle_and_parent(self) -> None:
        m = _manifest_with_one_asset()

        rs = build_report_set(initial=m, current=m, journal=[])
        vr = rs.variants[0]

        assert vr.schema_version == 2
        assert vr.variant_id == "variant_hd"
        assert vr.parent_kind is ParentKind.MOVIE
        assert vr.parent_id == "movie_blazar"
        assert vr.bundle_id == "bundle_hd"
        assert vr.asset_ids == ["asset_hd_main"]

    def test_bundle_lists_assets_and_sidecars(self) -> None:
        m = _manifest_with_one_asset()
        m.sidecars.append(
            ManifestSidecar(
                id="sidecar_0001",
                asset_id="asset_hd_main",
                kind=SidecarKind.SUBTITLE,
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
        """WHY: AssetReport.path_history must default to [] when no filesystem events ran."""
        m = _manifest_with_one_asset()

        rs = build_report_set(initial=m, current=m, journal=[])

        assert rs.assets[0].path_history == []

    def test_path_history_populated_for_move_asset(self) -> None:
        """WHY: a filesystem-affecting journal event must surface in path_history."""
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
        """WHY: AssetReport.version_history must default to [] when no version events ran."""
        m = _manifest_with_one_asset()

        rs = build_report_set(initial=m, current=m, journal=[])

        assert rs.assets[0].version_history == []

    def test_version_history_populated_for_reencode_video(self) -> None:
        """WHY: a version-affecting journal event must surface in version_history."""
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

    def test_asset_snapshot_uses_current_greatest_index_version(self) -> None:
        initial = _manifest_with_one_asset()
        current = _manifest_with_two_versions()

        rs = build_report_set(initial=initial, current=current, journal=[])

        assert rs.assets[0].current is not None
        assert rs.assets[0].current.version_id == "version_0002"
        assert rs.assets[0].current.version_index == 1

    def test_asset_snapshot_copies_hash_probe_and_corruption(self) -> None:
        initial = _manifest_with_one_asset()
        current = _manifest_with_two_versions()

        rs = build_report_set(initial=initial, current=current, journal=[])

        snapshot = rs.assets[0].current
        assert snapshot is not None
        assert snapshot.content_hash == "sha256:" + "1" * 64
        assert snapshot.probed == _probed_media()
        assert snapshot.corruption == _corruption_record()

    def test_asset_report_json_emits_current_corruption_metadata(self) -> None:
        initial = _manifest_with_one_asset()
        current = _manifest_with_two_versions()

        rs = build_report_set(initial=initial, current=current, journal=[])
        payload = rs.assets[0].model_dump(mode="json", exclude_none=True)

        assert payload["current"]["corruption"]["event_id"] == "corrupt_header_001"

    def test_iteration_order_is_stable(self) -> None:
        """Reports sort by id lexicographically.

        WHY: report files are written one per id; bit-identical fixtures
        require deterministic enumeration.
        """
        m = _manifest_with_one_asset()

        rs1 = build_report_set(initial=m, current=m, journal=[])
        rs2 = build_report_set(initial=m, current=m, journal=[])

        assert [a.asset_id for a in rs1.assets] == [a.asset_id for a in rs2.assets]
