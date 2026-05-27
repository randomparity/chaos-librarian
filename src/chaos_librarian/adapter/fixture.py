"""Fixture loader for adapter comparisons."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from pydantic import BaseModel, TypeAdapter, ValidationError

from chaos_librarian.adapter.errors import E_ADAPTER_FIXTURE_INVALID, AdapterInputError
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    ReplayBundle,
    compute_plan_only_run_id,
)
from chaos_librarian.contract.reports import (
    REPORT_FAMILIES,
    REPORT_FAMILY_NAMES,
    AlbumReport,
    ArtistReport,
    AssetReport,
    BundleReport,
    DiscReport,
    EpisodeReport,
    MovieReport,
    SeasonReport,
    SeriesReport,
    TrackReport,
    VariantReport,
)
from chaos_librarian.contract.run_sentinel import SENTINEL_FILENAME, RunSentinel
from chaos_librarian.engine import build_report_set
from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.validation import prepare_run_input_from_bytes

_REPLAY_ADAPTER: TypeAdapter[ReplayBundle] = TypeAdapter(ReplayBundle)
_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


@dataclass(frozen=True)
class OracleReports:
    """Report maps keyed by oracle entity id."""

    assets: Mapping[str, AssetReport]
    movies: Mapping[str, MovieReport]
    series: Mapping[str, SeriesReport]
    seasons: Mapping[str, SeasonReport]
    episodes: Mapping[str, EpisodeReport]
    artists: Mapping[str, ArtistReport]
    albums: Mapping[str, AlbumReport]
    discs: Mapping[str, DiscReport]
    tracks: Mapping[str, TrackReport]
    variants: Mapping[str, VariantReport]
    bundles: Mapping[str, BundleReport]


@dataclass(frozen=True)
class OracleFixture:
    """In-memory adapter view of one Chaos Librarian run directory."""

    run_dir: Path
    run_id: uuid.UUID
    scenario_id: str
    sentinel: RunSentinel
    replay_bundle: ReplayBundle
    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    reports: OracleReports


class SentinelInvalidError(ChaosLibrarianError):
    """Raised when a run-directory sentinel is missing or unparseable."""


def load_fixture(run_dir: Path) -> OracleFixture:
    """Load and cross-check a Chaos Librarian oracle fixture."""
    try:
        return _load_fixture_checked(run_dir)
    except AdapterInputError:
        raise
    except SentinelInvalidError:
        raise
    except (OSError, ValidationError, ValueError, ChaosLibrarianError) as exc:
        _fixture_invalid(f"fixture input is invalid: {exc}", path=run_dir)


def _load_fixture_checked(run_dir: Path) -> OracleFixture:
    sentinel = _verify_sentinel(run_dir)
    replay_bundle = _parse_replay(run_dir / "replay.json")
    scenario_bytes = (run_dir / "scenario.yaml").read_bytes()
    scenario_id = _parse_scenario_id(scenario_bytes, run_dir=run_dir)
    initial_manifest = _parse_model_json(run_dir / "manifest.initial.json", Manifest)
    current_manifest = _parse_model_json(run_dir / "manifest.current.json", Manifest)
    journal = tuple(_parse_journal(run_dir / "journal.jsonl"))

    _validate_fixture_consistency(
        run_dir=run_dir,
        sentinel=sentinel,
        replay_bundle=replay_bundle,
        scenario_bytes=scenario_bytes,
        scenario_id=scenario_id,
        journal=journal,
    )
    reports = _load_or_derive_reports(
        run_dir=run_dir,
        initial_manifest=initial_manifest,
        current_manifest=current_manifest,
        journal=journal,
    )
    return OracleFixture(
        run_dir=run_dir,
        run_id=replay_bundle.run_id,
        scenario_id=scenario_id,
        sentinel=sentinel,
        replay_bundle=replay_bundle,
        initial_manifest=initial_manifest,
        current_manifest=current_manifest,
        journal=journal,
        reports=reports,
    )


def _fixture_invalid(
    message: str,
    *,
    path: Path,
    details: Mapping[str, object] | None = None,
) -> NoReturn:
    merged_details: dict[str, object] = {"path": str(path)}
    if details:
        merged_details.update(details)
    raise AdapterInputError(
        error_code=E_ADAPTER_FIXTURE_INVALID,
        message=message,
        details=merged_details,
    )


def _parse_replay(path: Path) -> ReplayBundle:
    try:
        return _REPLAY_ADAPTER.validate_json(path.read_text())
    except (OSError, ValidationError, ValueError) as exc:
        _fixture_invalid(f"replay.json is invalid: {exc}", path=path)


def _parse_model_json[T: BaseModel](path: Path, model: type[T]) -> T:
    try:
        return model.model_validate_json(path.read_text())
    except (OSError, ValidationError, ValueError) as exc:
        _fixture_invalid(f"{path.name} is invalid: {exc}", path=path)


def _parse_scenario_id(scenario_bytes: bytes, *, run_dir: Path) -> str:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=f"adapter:{run_dir}",
    )
    return run_input.scenario.scenario_id


def _parse_journal(path: Path) -> list[JournalEntry]:
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        _fixture_invalid(f"journal.jsonl is invalid: {exc}", path=path)
    entries: list[JournalEntry] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entries.append(_JOURNAL_ADAPTER.validate_json(line))
        except ValidationError as exc:
            _fixture_invalid(
                f"journal.jsonl line {line_number} is invalid: {exc}",
                path=path,
                details={"line": line_number},
            )
    return entries


def _validate_fixture_consistency(
    *,
    run_dir: Path,
    sentinel: RunSentinel,
    replay_bundle: ReplayBundle,
    scenario_bytes: bytes,
    scenario_id: str,
    journal: tuple[JournalEntry, ...],
) -> None:
    if sentinel.run_id != replay_bundle.run_id:
        _fixture_invalid("sentinel run_id does not match replay.json", path=run_dir)
    if scenario_bytes != replay_bundle.scenario.encode("utf-8"):
        _fixture_invalid("scenario.yaml bytes do not match replay.json scenario", path=run_dir)
    if replay_bundle.execution_mode is ExecutionMode.PLAN_ONLY:
        _validate_plan_only_run_id(run_dir, replay_bundle, scenario_bytes)
    _validate_journal_identity(run_dir, replay_bundle, scenario_id, journal)
    _validate_journal_digest(run_dir, replay_bundle, journal)


def _validate_plan_only_run_id(
    run_dir: Path, replay_bundle: ReplayBundle, scenario_bytes: bytes
) -> None:
    content_hash = hashlib.sha256(scenario_bytes).hexdigest()
    recomputed = compute_plan_only_run_id(content_hash, replay_bundle.resolved_seed)
    if recomputed != replay_bundle.run_id:
        _fixture_invalid("plan-only run_id does not match scenario bytes and seed", path=run_dir)


def _validate_journal_identity(
    run_dir: Path,
    replay_bundle: ReplayBundle,
    scenario_id: str,
    journal: tuple[JournalEntry, ...],
) -> None:
    for line_number, entry in enumerate(journal, start=1):
        if entry.run_id != replay_bundle.run_id:
            _fixture_invalid(
                "journal run_id does not match replay.json",
                path=run_dir,
                details={"line": line_number},
            )
        if entry.scenario_id != scenario_id:
            _fixture_invalid(
                "journal scenario_id does not match scenario.yaml",
                path=run_dir,
                details={"line": line_number},
            )


def _validate_journal_digest(
    run_dir: Path, replay_bundle: ReplayBundle, journal: tuple[JournalEntry, ...]
) -> None:
    entries: tuple[JournalEntry, ...]
    if replay_bundle.execution_mode is ExecutionMode.RUN:
        entries = tuple(entry.model_copy(update={"wall_clock_time": None}) for entry in journal)
    else:
        entries = journal
    digest = hashlib.sha256(_serialize_journal_bytes(entries)).hexdigest()
    if digest != replay_bundle.journal_digest:
        _fixture_invalid("journal_digest does not match journal.jsonl", path=run_dir)


def _verify_sentinel(run_dir: Path) -> RunSentinel:
    target = run_dir / SENTINEL_FILENAME
    if not target.exists():
        raise SentinelInvalidError(f"sentinel missing: {target}")
    try:
        return RunSentinel.model_validate_json(target.read_text())
    except (OSError, ValidationError, ValueError) as exc:
        raise SentinelInvalidError(f"sentinel unparseable: {exc}") from exc


def _serialize_journal_bytes(entries: tuple[JournalEntry, ...]) -> bytes:
    chunks: list[bytes] = []
    for entry in entries:
        chunks.append(entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))
        chunks.append(b"\n")
    return b"".join(chunks)


def _load_or_derive_reports(
    *,
    run_dir: Path,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal: tuple[JournalEntry, ...],
) -> OracleReports:
    reports_dir = run_dir / "reports"
    if not reports_dir.exists():
        return _reports_from_report_set(
            build_report_set(initial=initial_manifest, current=current_manifest, journal=journal)
        )
    return _load_present_reports(reports_dir, initial_manifest)


def _reports_from_report_set(report_set: Any) -> OracleReports:
    maps = {
        family.name: _required_report_map(report_set, family.name, family.id_field)
        for family in REPORT_FAMILIES
    }
    return OracleReports(**maps)


def _required_report_map(report_set: Any, name: str, id_field: str) -> dict[str, Any]:
    if not hasattr(report_set, name):
        raise ValueError(f"report set is missing required {name} reports")
    return {getattr(report, id_field): report for report in getattr(report_set, name)}


def _load_present_reports(reports_dir: Path, initial_manifest: Manifest) -> OracleReports:
    present_names = {path.name for path in reports_dir.iterdir() if path.is_dir()}
    expected_names = set(REPORT_FAMILY_NAMES)
    if present_names != expected_names:
        _fixture_invalid(
            "reports directory set does not match required report families",
            path=reports_dir,
            details={
                "missing": sorted(expected_names - present_names),
                "extra": sorted(present_names - expected_names),
            },
        )
    reports = OracleReports(
        assets=_load_report_map(reports_dir / "assets", AssetReport, "asset_id"),
        movies=_load_report_map(reports_dir / "movies", MovieReport, "movie_id"),
        series=_load_report_map(reports_dir / "series", SeriesReport, "series_id"),
        seasons=_load_report_map(reports_dir / "seasons", SeasonReport, "season_id"),
        episodes=_load_report_map(reports_dir / "episodes", EpisodeReport, "episode_id"),
        artists=_load_report_map(reports_dir / "artists", ArtistReport, "artist_id"),
        albums=_load_report_map(reports_dir / "albums", AlbumReport, "album_id"),
        discs=_load_report_map(reports_dir / "discs", DiscReport, "disc_id"),
        tracks=_load_report_map(reports_dir / "tracks", TrackReport, "track_id"),
        variants=_load_report_map(reports_dir / "variants", VariantReport, "variant_id"),
        bundles=_load_report_map(reports_dir / "bundles", BundleReport, "bundle_id"),
    )
    _validate_report_ids(reports, initial_manifest, reports_dir)
    return reports


def _load_report_map[T: BaseModel](directory: Path, model: type[T], id_field: str) -> dict[str, T]:
    reports: dict[str, T] = {}
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            _fixture_invalid("report directory contains a non-report entry", path=path)
        report = _parse_model_json(path, model)
        report_id = getattr(report, id_field)
        if not isinstance(report_id, str):
            _fixture_invalid(f"report {id_field} is invalid", path=path)
        if path.stem != report_id:
            _fixture_invalid("report filename stem does not match report id", path=path)
        reports[report_id] = report
    return reports


def _validate_report_ids(
    reports: OracleReports, initial_manifest: Manifest, reports_dir: Path
) -> None:
    _require_exact_report_ids(
        set(reports.assets),
        {asset.id for asset in initial_manifest.assets},
        reports_dir / "assets",
    )
    _require_exact_report_ids(
        set(reports.movies),
        {movie.id for movie in initial_manifest.movies},
        reports_dir / "movies",
    )
    _require_exact_report_ids(
        set(reports.series),
        {series.id for series in initial_manifest.series},
        reports_dir / "series",
    )
    _require_exact_report_ids(
        set(reports.seasons),
        {season.id for season in initial_manifest.seasons},
        reports_dir / "seasons",
    )
    _require_exact_report_ids(
        set(reports.episodes),
        {episode.id for episode in initial_manifest.episodes},
        reports_dir / "episodes",
    )
    _require_exact_report_ids(
        set(reports.artists),
        {artist.id for artist in initial_manifest.artists},
        reports_dir / "artists",
    )
    _require_exact_report_ids(
        set(reports.albums),
        {album.id for album in initial_manifest.albums},
        reports_dir / "albums",
    )
    _require_exact_report_ids(
        set(reports.discs),
        {disc.id for disc in initial_manifest.discs},
        reports_dir / "discs",
    )
    _require_exact_report_ids(
        set(reports.tracks),
        {track.id for track in initial_manifest.tracks},
        reports_dir / "tracks",
    )
    _require_exact_report_ids(
        set(reports.variants),
        {variant.id for variant in initial_manifest.variants},
        reports_dir / "variants",
    )
    _require_exact_report_ids(
        set(reports.bundles),
        {bundle.id for bundle in initial_manifest.bundles},
        reports_dir / "bundles",
    )


def _require_exact_report_ids(actual: set[str], expected: set[str], path: Path) -> None:
    if actual != expected:
        _fixture_invalid(
            "present reports do not exactly match initial manifest ids",
            path=path,
            details={
                "missing": sorted(expected - actual),
                "extra": sorted(actual - expected),
            },
        )
