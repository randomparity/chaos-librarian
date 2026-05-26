"""Shared adapter test fixtures."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from chaos_librarian.adapter.fixture import OracleFixture, OracleReports
from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.journal import AtomicJournalEntry, JournalEntry
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
from chaos_librarian.contract.observed_state import (
    ObservedAlbum,
    ObservedArtist,
    ObservedAsset,
    ObservedBundle,
    ObservedConsumer,
    ObservedDisc,
    ObservedEpisode,
    ObservedMovie,
    ObservedSeason,
    ObservedSeries,
    ObservedSidecar,
    ObservedState,
    ObservedTrack,
    ObservedVariant,
)
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle, compute_plan_only_run_id
from chaos_librarian.contract.reports import (
    AlbumReport,
    ArtistReport,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    DiscReport,
    EpisodeReport,
    MovieReport,
    SeasonReport,
    SeriesReport,
    TrackReport,
    VariantReport,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

RUN_ID = uuid.UUID("7c44eb62-7046-4b8f-a168-eaf3a58e0145")
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
_SYNTHETIC_SCENARIOS = frozenset({"static-library.yaml"})
_REPORT_DIRS = (
    "assets",
    "movies",
    "series",
    "seasons",
    "episodes",
    "artists",
    "albums",
    "discs",
    "tracks",
    "variants",
    "bundles",
)


@dataclass(frozen=True)
class _ManifestTopology:
    movies: list[ManifestMovie]
    series: list[ManifestSeries]
    seasons: list[ManifestSeason]
    episodes: list[ManifestEpisode]
    artists: list[ManifestArtist]
    albums: list[ManifestAlbum]
    discs: list[ManifestDisc]
    tracks: list[ManifestTrack]
    variants: list[ManifestVariant]


@dataclass(frozen=True)
class _ReportTopology:
    movies: dict[str, MovieReport]
    series: dict[str, SeriesReport]
    seasons: dict[str, SeasonReport]
    episodes: dict[str, EpisodeReport]
    artists: dict[str, ArtistReport]
    albums: dict[str, AlbumReport]
    discs: dict[str, DiscReport]
    tracks: dict[str, TrackReport]
    variants: dict[str, VariantReport]


@dataclass(frozen=True)
class _ObservedRefs:
    movies: dict[str, str]
    series: dict[str, str]
    seasons: dict[str, str]
    episodes: dict[str, str]
    artists: dict[str, str]
    albums: dict[str, str]
    discs: dict[str, str]
    tracks: dict[str, str]
    variants: dict[str, str]
    bundles: dict[str, str]


@dataclass(frozen=True)
class _ObservedDomainRows:
    movies: list[ObservedMovie]
    series: list[ObservedSeries]
    seasons: list[ObservedSeason]
    episodes: list[ObservedEpisode]
    artists: list[ObservedArtist]
    albums: list[ObservedAlbum]
    discs: list[ObservedDisc]
    tracks: list[ObservedTrack]


def scenario_bytes(name: str) -> bytes:
    if name in _SYNTHETIC_SCENARIOS:
        return _scenario_bytes_from_id(name.removesuffix(".yaml"))
    return (Path("tests/fixtures/scenarios") / name).read_bytes()


def write_plan_fixture(tmp_path: Path, scenario_name: str = "identity-move-rename.yaml") -> Path:
    scenario_yaml_bytes = scenario_bytes(scenario_name)
    if scenario_name in _SYNTHETIC_SCENARIOS:
        run_dir = tmp_path / "run"
        _write_synthetic_plan_fixture(run_dir, scenario_yaml_bytes)
        return run_dir

    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_yaml_bytes,
        source_label=f"test:{scenario_name}",
    )
    validation_report = run_validation(run_input)
    assert validation_report.ok
    # Lazy until engine cleanup lands, so adapter-only tests can import helpers.
    from chaos_librarian.engine import run_plan  # noqa: PLC0415
    from chaos_librarian.engine.writer import write_fixture  # noqa: PLC0415

    artifacts = run_plan(run_input=run_input, validation_report=validation_report)
    run_dir = tmp_path / "run"
    write_fixture(run_dir, artifacts, scenario_yaml_bytes)
    return run_dir


def _scenario_bytes_from_id(scenario_id: str) -> bytes:
    return f"""schema_version: 12
scenario_id: {scenario_id}
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: movie-a
    title: Synthetic
    layout: movie_flat
    variants:
      - id: variant-a
        label: hd
        bundle:
          id: bundle-a
          assets:
            - id: asset-a
              role: primary_video
              container: mkv
              duration_seconds: 60.0
series: []
artists: []
timeline: []
""".encode()


def _write_synthetic_plan_fixture(run_dir: Path, scenario_yaml_bytes: bytes) -> None:
    scenario_id = scenario_yaml_bytes.decode().split("scenario_id: ", 1)[1].split("\n", 1)[0]
    content_hash = hashlib.sha256(scenario_yaml_bytes).hexdigest()
    run_id = compute_plan_only_run_id(content_hash, 1)
    journal = [
        AtomicJournalEntry(
            schema_version=1,
            event_id="fixture-001",
            scenario_id=scenario_id,
            run_id=run_id,
            logical_time_ns=0,
            action="fixture",
            target_ids=["asset-a"],
        )
    ]
    replay = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario=scenario_yaml_bytes.decode(),
        run_id=run_id,
        resolved_seed=1,
        applied_events=len(journal),
        journal_digest=hashlib.sha256(_serialize_journal_bytes(journal)).hexdigest(),
    )
    sentinel = RunSentinel(
        schema_version=2,
        run_id=run_id,
        created_by="chaos-librarian",
        created_at=datetime(2026, 5, 22, tzinfo=UTC),
    )
    run_dir.mkdir()
    (run_dir / "scenario.yaml").write_bytes(scenario_yaml_bytes)
    _write_json(run_dir / "replay.json", replay)
    _write_json(run_dir / "manifest.initial.json", manifest())
    _write_json(run_dir / "manifest.current.json", manifest())
    (run_dir / "journal.jsonl").write_bytes(_serialize_journal_bytes(journal))
    _write_json(
        run_dir / "validation.json",
        ValidationReport(schema_version=1, scenario_id=scenario_id, ok=True),
    )
    _write_reports(run_dir / "reports", reports())
    _write_json(run_dir / ".chaos-librarian-run", sentinel)


def _write_reports(reports_dir: Path, oracle_reports: OracleReports) -> None:
    reports_dir.mkdir()
    for name in _REPORT_DIRS:
        directory = reports_dir / name
        directory.mkdir()
        for report_id, report in getattr(oracle_reports, name).items():
            _write_json(directory / f"{report_id}.json", report)


def _write_json(path: Path, model: BaseModel) -> None:
    path.write_text(model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n")


def _serialize_journal_bytes(entries: Iterable[JournalEntry]) -> bytes:
    chunks: list[bytes] = []
    for entry in entries:
        chunks.append(entry.model_dump_json(by_alias=True, exclude_none=True).encode())
        chunks.append(b"\n")
    return b"".join(chunks)


def probe(*, duration: float = 60.0, codec: str = "h264") -> ProbedMedia:
    return ProbedMedia(
        container="matroska,webm",
        duration_seconds=duration,
        size_bytes=12345,
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec=codec, width=1920, height=1080)],
    )


def _movie_manifest_topology() -> _ManifestTopology:
    return _ManifestTopology(
        movies=[ManifestMovie(id="movie-a", title="Synthetic", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="variant-a",
                parent_kind=ParentKind.MOVIE,
                parent_id="movie-a",
                label="hd",
            )
        ],
    )


def _episode_manifest_topology() -> _ManifestTopology:
    return _ManifestTopology(
        movies=[],
        series=[
            ManifestSeries(
                id="series-a",
                title="Starline",
                layout="season_folders",
                episode_naming="sxxexx_title",
            )
        ],
        seasons=[
            ManifestSeason(
                id="season-a",
                series_id="series-a",
                season_number=1,
                title="Season 1",
            )
        ],
        episodes=[
            ManifestEpisode(
                id="episode-a",
                season_id="season-a",
                episode_number=1,
                title="Pilot",
            )
        ],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="variant-a",
                parent_kind=ParentKind.EPISODE,
                parent_id="episode-a",
                label="hd",
            )
        ],
    )


def _track_manifest_topology() -> _ManifestTopology:
    return _ManifestTopology(
        movies=[],
        series=[],
        seasons=[],
        episodes=[],
        artists=[
            ManifestArtist(
                id="artist-a",
                name="North Index",
                layout="artist_album_disc",
                track_naming="track_number_title",
            )
        ],
        albums=[
            ManifestAlbum(
                id="album-a",
                artist_id="artist-a",
                title="Winter Index",
            )
        ],
        discs=[ManifestDisc(id="disc-a", album_id="album-a", disc_number=1)],
        tracks=[
            ManifestTrack(
                id="track-a",
                disc_id="disc-a",
                track_number=1,
                title="Opening",
            )
        ],
        variants=[
            ManifestVariant(
                id="variant-a",
                parent_kind=ParentKind.TRACK,
                parent_id="track-a",
                label="lossless",
            )
        ],
    )


def _manifest_topology(parent_kind: ParentKind) -> _ManifestTopology:
    if parent_kind is ParentKind.MOVIE:
        return _movie_manifest_topology()
    if parent_kind is ParentKind.EPISODE:
        return _episode_manifest_topology()
    if parent_kind is ParentKind.TRACK:
        return _track_manifest_topology()
    raise ValueError(f"Unsupported parent_kind: {parent_kind}")


def manifest(
    *,
    current_path: str | None = "library/Synthetic.mkv",
    content_hash: str | None = HASH_A,
    probed: ProbedMedia | None = None,
    sidecars: tuple[ManifestSidecar, ...] = (),
    parent_kind: ParentKind = ParentKind.MOVIE,
) -> Manifest:
    topology = _manifest_topology(parent_kind)
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=topology.movies,
        series=topology.series,
        seasons=topology.seasons,
        episodes=topology.episodes,
        artists=topology.artists,
        albums=topology.albums,
        discs=topology.discs,
        tracks=topology.tracks,
        variants=topology.variants,
        bundles=[ManifestBundle(id="bundle-a", variant_id="variant-a")],
        assets=[
            ManifestAsset(
                id="asset-a",
                bundle_id="bundle-a",
                role="main",
                container="mkv",
                duration_seconds=60.0,
            )
        ],
        versions=[
            ManifestVersion(
                id="version-a",
                asset_id="asset-a",
                index=0,
                content_hash=content_hash,
                probed=probed,
            )
        ],
        locations=(
            [ManifestLocation(id="location-a", asset_id="asset-a", path=current_path)]
            if current_path is not None
            else []
        ),
        sidecars=list(sidecars),
    )


def _asset_report(
    parent_kind: ParentKind,
    *,
    initial_snapshot: AssetSnapshot,
    current_snapshot: AssetSnapshot | None,
) -> AssetReport:
    if parent_kind is ParentKind.MOVIE:
        return AssetReport(
            schema_version=ASSET_REPORT_SCHEMA_VERSION,
            asset_id="asset-a",
            parent_kind=ParentKind.MOVIE,
            parent_id="movie-a",
            movie_id="movie-a",
            variant_id="variant-a",
            bundle_id="bundle-a",
            initial=initial_snapshot,
            history=[],
            current=current_snapshot,
        )
    if parent_kind is ParentKind.EPISODE:
        return AssetReport(
            schema_version=ASSET_REPORT_SCHEMA_VERSION,
            asset_id="asset-a",
            parent_kind=ParentKind.EPISODE,
            parent_id="episode-a",
            series_id="series-a",
            season_id="season-a",
            episode_id="episode-a",
            variant_id="variant-a",
            bundle_id="bundle-a",
            initial=initial_snapshot,
            history=[],
            current=current_snapshot,
        )
    if parent_kind is ParentKind.TRACK:
        return AssetReport(
            schema_version=ASSET_REPORT_SCHEMA_VERSION,
            asset_id="asset-a",
            parent_kind=ParentKind.TRACK,
            parent_id="track-a",
            artist_id="artist-a",
            album_id="album-a",
            disc_id="disc-a",
            track_id="track-a",
            variant_id="variant-a",
            bundle_id="bundle-a",
            initial=initial_snapshot,
            history=[],
            current=current_snapshot,
        )
    raise ValueError(f"Unsupported parent_kind: {parent_kind}")


def _movie_report_topology() -> _ReportTopology:
    return _ReportTopology(
        movies={
            "movie-a": MovieReport(
                schema_version=1,
                movie_id="movie-a",
                title="Synthetic",
                variant_ids=["variant-a"],
                asset_ids=["asset-a"],
            )
        },
        series={},
        seasons={},
        episodes={},
        artists={},
        albums={},
        discs={},
        tracks={},
        variants={
            "variant-a": VariantReport(
                schema_version=2,
                variant_id="variant-a",
                parent_kind=ParentKind.MOVIE,
                parent_id="movie-a",
                label="hd",
                bundle_id="bundle-a",
                asset_ids=["asset-a"],
            )
        },
    )


def _episode_report_topology() -> _ReportTopology:
    return _ReportTopology(
        movies={},
        series={
            "series-a": SeriesReport(
                schema_version=1,
                series_id="series-a",
                title="Starline",
                season_ids=["season-a"],
                episode_ids=["episode-a"],
                asset_ids=["asset-a"],
            )
        },
        seasons={
            "season-a": SeasonReport(
                schema_version=1,
                season_id="season-a",
                series_id="series-a",
                season_number=1,
                title="Season 1",
                episode_ids=["episode-a"],
                asset_ids=["asset-a"],
            )
        },
        episodes={
            "episode-a": EpisodeReport(
                schema_version=1,
                episode_id="episode-a",
                season_id="season-a",
                episode_number=1,
                title="Pilot",
                variant_ids=["variant-a"],
                asset_ids=["asset-a"],
            )
        },
        artists={},
        albums={},
        discs={},
        tracks={},
        variants={
            "variant-a": VariantReport(
                schema_version=2,
                variant_id="variant-a",
                parent_kind=ParentKind.EPISODE,
                parent_id="episode-a",
                label="hd",
                bundle_id="bundle-a",
                asset_ids=["asset-a"],
            )
        },
    )


def _track_report_topology() -> _ReportTopology:
    return _ReportTopology(
        movies={},
        series={},
        seasons={},
        episodes={},
        artists={
            "artist-a": ArtistReport(
                schema_version=1,
                artist_id="artist-a",
                name="North Index",
                album_ids=["album-a"],
                track_ids=["track-a"],
                asset_ids=["asset-a"],
            )
        },
        albums={
            "album-a": AlbumReport(
                schema_version=1,
                album_id="album-a",
                artist_id="artist-a",
                title="Winter Index",
                disc_ids=["disc-a"],
                track_ids=["track-a"],
                asset_ids=["asset-a"],
            )
        },
        discs={
            "disc-a": DiscReport(
                schema_version=1,
                disc_id="disc-a",
                album_id="album-a",
                disc_number=1,
                track_ids=["track-a"],
                asset_ids=["asset-a"],
            )
        },
        tracks={
            "track-a": TrackReport(
                schema_version=1,
                track_id="track-a",
                disc_id="disc-a",
                track_number=1,
                title="Opening",
                performers=[],
                variant_ids=["variant-a"],
                asset_ids=["asset-a"],
            )
        },
        variants={
            "variant-a": VariantReport(
                schema_version=2,
                variant_id="variant-a",
                parent_kind=ParentKind.TRACK,
                parent_id="track-a",
                label="lossless",
                bundle_id="bundle-a",
                asset_ids=["asset-a"],
            )
        },
    )


def _report_topology(parent_kind: ParentKind) -> _ReportTopology:
    if parent_kind is ParentKind.MOVIE:
        return _movie_report_topology()
    if parent_kind is ParentKind.EPISODE:
        return _episode_report_topology()
    if parent_kind is ParentKind.TRACK:
        return _track_report_topology()
    raise ValueError(f"Unsupported parent_kind: {parent_kind}")


def reports(
    current_path: str | None = "library/Synthetic.mkv",
    *,
    parent_kind: ParentKind = ParentKind.MOVIE,
) -> OracleReports:
    initial_snapshot = AssetSnapshot(
        location_path="library/Synthetic.mkv",
        version_id="version-a",
        version_index=0,
        content_hash=HASH_A,
    )
    current_snapshot = (
        AssetSnapshot(
            location_path=current_path,
            version_id="version-a",
            version_index=0,
            content_hash=HASH_A,
        )
        if current_path is not None
        else None
    )
    topology = _report_topology(parent_kind)
    return OracleReports(
        assets={
            "asset-a": _asset_report(
                parent_kind,
                initial_snapshot=initial_snapshot,
                current_snapshot=current_snapshot,
            )
        },
        movies=topology.movies,
        series=topology.series,
        seasons=topology.seasons,
        episodes=topology.episodes,
        artists=topology.artists,
        albums=topology.albums,
        discs=topology.discs,
        tracks=topology.tracks,
        variants=topology.variants,
        bundles={
            "bundle-a": BundleReport(
                schema_version=1,
                bundle_id="bundle-a",
                variant_id="variant-a",
                asset_ids=["asset-a"],
            )
        },
    )


def fixture(
    *,
    current_path: str | None = "library/Synthetic.mkv",
    content_hash: str | None = HASH_A,
    probed: ProbedMedia | None = None,
    sidecars: tuple[ManifestSidecar, ...] = (),
    parent_kind: ParentKind = ParentKind.MOVIE,
) -> OracleFixture:
    current_manifest = manifest(
        current_path=current_path,
        content_hash=content_hash,
        probed=probed,
        sidecars=sidecars,
        parent_kind=parent_kind,
    )
    return OracleFixture(
        run_dir=Path("/tmp/chaos-run"),
        run_id=RUN_ID,
        scenario_id="scenario-a",
        sentinel=RunSentinel(
            schema_version=2,
            run_id=RUN_ID,
            created_by="chaos-librarian",
            created_at=datetime(2026, 5, 22, tzinfo=UTC),
        ),
        replay_bundle=PlanOnlyReplayBundle(
            schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
            chaos_librarian_version="0.0.0",
            scenario="scenario: bytes",
            run_id=RUN_ID,
            resolved_seed=1,
            applied_events=0,
            journal_digest="0" * 64,
        ),
        initial_manifest=manifest(parent_kind=parent_kind),
        current_manifest=current_manifest,
        journal=(),
        reports=reports(current_path, parent_kind=parent_kind),
    )


def observed(
    *,
    run_id: uuid.UUID = RUN_ID,
    current_path: str | None = "library/Synthetic.mkv",
    content_hash: str | None = HASH_A,
    probed: ProbedMedia | None = None,
    sidecars: tuple[ObservedSidecar, ...] = (),
    topology_label: str = "hd",
) -> ObservedState:
    return ObservedState(
        schema_version=2,
        consumer=ObservedConsumer(name="voom-v2", version="0.9.0"),
        run_id=run_id,
        observed_at=datetime(2026, 5, 22, tzinfo=UTC),
        assets=[
            ObservedAsset(
                observed_ref="observed-a",
                current_path=current_path,
                content_hash=content_hash,
                probed=probed,
                variant_ref="consumer-variant",
                bundle_ref="consumer-bundle",
                sidecars=list(sidecars),
            )
        ],
        movies=[ObservedMovie(observed_ref="consumer-movie", title="Synthetic")],
        variants=[
            ObservedVariant(
                observed_ref="consumer-variant",
                parent_kind=ParentKind.MOVIE,
                parent_ref="consumer-movie",
                label=topology_label,
            )
        ],
        bundles=[
            ObservedBundle(
                observed_ref="consumer-bundle",
                variant_ref="consumer-variant",
                asset_refs=["observed-a"],
            )
        ],
    )


def _observed_refs(current_manifest: Manifest) -> _ObservedRefs:
    return _ObservedRefs(
        movies={movie.id: f"observed-{movie.id}" for movie in current_manifest.movies},
        series={series.id: f"observed-{series.id}" for series in current_manifest.series},
        seasons={season.id: f"observed-{season.id}" for season in current_manifest.seasons},
        episodes={episode.id: f"observed-{episode.id}" for episode in current_manifest.episodes},
        artists={artist.id: f"observed-{artist.id}" for artist in current_manifest.artists},
        albums={album.id: f"observed-{album.id}" for album in current_manifest.albums},
        discs={disc.id: f"observed-{disc.id}" for disc in current_manifest.discs},
        tracks={track.id: f"observed-{track.id}" for track in current_manifest.tracks},
        variants={variant.id: f"observed-{variant.id}" for variant in current_manifest.variants},
        bundles={bundle.id: f"observed-{bundle.id}" for bundle in current_manifest.bundles},
    )


def _observed_sidecars_by_asset(current_manifest: Manifest) -> dict[str, list[ObservedSidecar]]:
    sidecars_by_asset: dict[str, list[ObservedSidecar]] = {}
    for sidecar in current_manifest.sidecars:
        sidecars_by_asset.setdefault(sidecar.asset_id, []).append(
            ObservedSidecar(
                observed_ref=f"observed-{sidecar.id}",
                kind=sidecar.kind,
                path=sidecar.path,
                content_hash=sidecar.content_hash,
            )
        )
    return sidecars_by_asset


def _observed_assets_from_manifest(
    current_manifest: Manifest,
    *,
    refs: _ObservedRefs,
    include_current_paths: bool,
    include_topology: bool,
    path_override: str | None,
) -> tuple[list[ObservedAsset], dict[str, list[str]]]:
    locations = {location.asset_id: location for location in current_manifest.locations}
    versions = {version.asset_id: version for version in current_manifest.versions}
    bundles_by_id = {bundle.id: bundle for bundle in current_manifest.bundles}
    asset_refs_by_bundle: dict[str, list[str]] = {}
    sidecars_by_asset = _observed_sidecars_by_asset(current_manifest)
    assets: list[ObservedAsset] = []
    for asset in current_manifest.assets:
        location = locations.get(asset.id)
        version = versions.get(asset.id)
        bundle = bundles_by_id[asset.bundle_id]
        observed_ref = f"observed-{asset.id}"
        asset_refs_by_bundle.setdefault(asset.bundle_id, []).append(observed_ref)
        current_path = location.path if location is not None and include_current_paths else None
        if include_current_paths and path_override is not None and not assets:
            current_path = path_override
        assets.append(
            ObservedAsset(
                observed_ref=observed_ref,
                current_path=current_path,
                content_hash=version.content_hash if version is not None else None,
                probed=version.probed if version is not None else None,
                variant_ref=refs.variants[bundle.variant_id] if include_topology else None,
                bundle_ref=refs.bundles[asset.bundle_id] if include_topology else None,
                sidecars=sidecars_by_asset.get(asset.id, []),
            )
        )
    return assets, asset_refs_by_bundle


def _observed_domain_rows(current_manifest: Manifest, refs: _ObservedRefs) -> _ObservedDomainRows:
    movies = [
        ObservedMovie(observed_ref=refs.movies[movie.id], title=movie.title)
        for movie in current_manifest.movies
    ]
    series = [
        ObservedSeries(observed_ref=refs.series[series.id], title=series.title)
        for series in current_manifest.series
    ]
    seasons = [
        ObservedSeason(
            observed_ref=refs.seasons[season.id],
            series_ref=refs.series[season.series_id],
            season_number=season.season_number,
            title=season.title,
        )
        for season in current_manifest.seasons
    ]
    episodes = [
        ObservedEpisode(
            observed_ref=refs.episodes[episode.id],
            season_ref=refs.seasons[episode.season_id],
            episode_number=episode.episode_number,
            title=episode.title,
            aired_on=episode.aired_on,
            absolute_number=episode.absolute_number,
        )
        for episode in current_manifest.episodes
    ]
    artists = [
        ObservedArtist(observed_ref=refs.artists[artist.id], name=artist.name)
        for artist in current_manifest.artists
    ]
    albums = [
        ObservedAlbum(
            observed_ref=refs.albums[album.id],
            artist_ref=refs.artists[album.artist_id],
            title=album.title,
            release_year=album.release_year,
        )
        for album in current_manifest.albums
    ]
    discs = [
        ObservedDisc(
            observed_ref=refs.discs[disc.id],
            album_ref=refs.albums[disc.album_id],
            disc_number=disc.disc_number,
        )
        for disc in current_manifest.discs
    ]
    tracks = [
        ObservedTrack(
            observed_ref=refs.tracks[track.id],
            disc_ref=refs.discs[track.disc_id],
            track_number=track.track_number,
            title=track.title,
            performers=list(track.performers),
        )
        for track in current_manifest.tracks
    ]
    return _ObservedDomainRows(
        movies=movies,
        series=series,
        seasons=seasons,
        episodes=episodes,
        artists=artists,
        albums=albums,
        discs=discs,
        tracks=tracks,
    )


def _observed_variants(current_manifest: Manifest, refs: _ObservedRefs) -> list[ObservedVariant]:
    return [
        ObservedVariant(
            observed_ref=refs.variants[variant.id],
            parent_kind=variant.parent_kind,
            parent_ref=_parent_ref_for_variant(
                variant.parent_kind,
                variant.parent_id,
                movie_refs=refs.movies,
                episode_refs=refs.episodes,
                track_refs=refs.tracks,
            ),
            label=variant.label,
        )
        for variant in current_manifest.variants
    ]


def _observed_bundles(
    current_manifest: Manifest,
    *,
    refs: _ObservedRefs,
    asset_refs_by_bundle: dict[str, list[str]],
) -> list[ObservedBundle]:
    return [
        ObservedBundle(
            observed_ref=refs.bundles[bundle.id],
            variant_ref=refs.variants[bundle.variant_id],
            asset_refs=asset_refs_by_bundle.get(bundle.id, []),
        )
        for bundle in current_manifest.bundles
    ]


def observed_from_fixture(
    oracle_fixture: OracleFixture,
    *,
    run_id: uuid.UUID | None = None,
    path_override: str | None = None,
    include_current_paths: bool = True,
    include_topology: bool = False,
) -> ObservedState:
    current_manifest = oracle_fixture.current_manifest
    refs = _observed_refs(current_manifest)
    assets, asset_refs_by_bundle = _observed_assets_from_manifest(
        current_manifest,
        refs=refs,
        include_current_paths=include_current_paths,
        include_topology=include_topology,
        path_override=path_override,
    )
    domain_rows = _observed_domain_rows(current_manifest, refs)
    variants = _observed_variants(current_manifest, refs)
    bundles = _observed_bundles(
        current_manifest,
        refs=refs,
        asset_refs_by_bundle=asset_refs_by_bundle,
    )
    return ObservedState(
        schema_version=2,
        consumer=ObservedConsumer(name="voom-v2", version="0.9.0"),
        run_id=run_id or oracle_fixture.run_id,
        observed_at=oracle_fixture.sentinel.created_at or datetime(2026, 5, 22, tzinfo=UTC),
        assets=assets,
        movies=domain_rows.movies if include_topology else [],
        series=domain_rows.series if include_topology else [],
        seasons=domain_rows.seasons if include_topology else [],
        episodes=domain_rows.episodes if include_topology else [],
        artists=domain_rows.artists if include_topology else [],
        albums=domain_rows.albums if include_topology else [],
        discs=domain_rows.discs if include_topology else [],
        tracks=domain_rows.tracks if include_topology else [],
        variants=variants if include_topology else [],
        bundles=bundles if include_topology else [],
    )


def _parent_ref_for_variant(
    parent_kind: ParentKind,
    parent_id: str,
    *,
    movie_refs: dict[str, str],
    episode_refs: dict[str, str],
    track_refs: dict[str, str],
) -> str:
    if parent_kind is ParentKind.MOVIE:
        return movie_refs[parent_id]
    if parent_kind is ParentKind.EPISODE:
        return episode_refs[parent_id]
    return track_refs[parent_id]
