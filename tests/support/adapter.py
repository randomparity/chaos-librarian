"""Shared adapter test fixtures."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
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
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestMovie,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ProbedMedia,
    ProbedStream,
    StreamKind,
)
from chaos_librarian.contract.observed_state import (
    ObservedAsset,
    ObservedBundle,
    ObservedConsumer,
    ObservedMovie,
    ObservedSidecar,
    ObservedState,
    ObservedVariant,
)
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle, compute_plan_only_run_id
from chaos_librarian.contract.reports import (
    AssetReport,
    AssetSnapshot,
    BundleReport,
    MovieReport,
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


def manifest(
    *,
    current_path: str | None = "library/Synthetic.mkv",
    content_hash: str | None = HASH_A,
    probed: ProbedMedia | None = None,
    sidecars: tuple[ManifestSidecar, ...] = (),
) -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
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


def reports(current_path: str | None = "library/Synthetic.mkv") -> OracleReports:
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
    return OracleReports(
        assets={
            "asset-a": AssetReport(
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
        },
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
) -> OracleFixture:
    current_manifest = manifest(
        current_path=current_path,
        content_hash=content_hash,
        probed=probed,
        sidecars=sidecars,
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
        initial_manifest=manifest(),
        current_manifest=current_manifest,
        journal=(),
        reports=reports(current_path),
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


def observed_from_fixture(
    oracle_fixture: OracleFixture,
    *,
    run_id: uuid.UUID | None = None,
    path_override: str | None = None,
    include_current_paths: bool = True,
    include_topology: bool = False,
) -> ObservedState:
    locations = {
        location.asset_id: location for location in oracle_fixture.current_manifest.locations
    }
    versions = {version.asset_id: version for version in oracle_fixture.current_manifest.versions}
    movie_refs = {
        movie.id: f"observed-{movie.id}" for movie in oracle_fixture.current_manifest.movies
    }
    episode_refs = {
        episode.id: f"observed-{episode.id}" for episode in oracle_fixture.current_manifest.episodes
    }
    track_refs = {
        track.id: f"observed-{track.id}" for track in oracle_fixture.current_manifest.tracks
    }
    variant_refs = {
        variant.id: f"observed-{variant.id}" for variant in oracle_fixture.current_manifest.variants
    }
    bundle_refs = {
        bundle.id: f"observed-{bundle.id}" for bundle in oracle_fixture.current_manifest.bundles
    }
    bundles_by_id = {bundle.id: bundle for bundle in oracle_fixture.current_manifest.bundles}
    asset_refs_by_bundle: dict[str, list[str]] = {}
    sidecars_by_asset: dict[str, list[ObservedSidecar]] = {}
    for sidecar in oracle_fixture.current_manifest.sidecars:
        sidecars_by_asset.setdefault(sidecar.asset_id, []).append(
            ObservedSidecar(
                observed_ref=f"observed-{sidecar.id}",
                kind=sidecar.kind,
                path=sidecar.path,
                content_hash=sidecar.content_hash,
            )
        )
    assets: list[ObservedAsset] = []
    for asset in oracle_fixture.current_manifest.assets:
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
                variant_ref=variant_refs[bundle.variant_id] if include_topology else None,
                bundle_ref=bundle_refs[asset.bundle_id] if include_topology else None,
                sidecars=sidecars_by_asset.get(asset.id, []),
            )
        )
    movies = [
        ObservedMovie(observed_ref=movie_refs[movie.id], title=movie.title)
        for movie in oracle_fixture.current_manifest.movies
    ]
    variants = [
        ObservedVariant(
            observed_ref=variant_refs[variant.id],
            parent_kind=variant.parent_kind,
            parent_ref=_parent_ref_for_variant(
                variant.parent_kind,
                variant.parent_id,
                movie_refs=movie_refs,
                episode_refs=episode_refs,
                track_refs=track_refs,
            ),
            label=variant.label,
        )
        for variant in oracle_fixture.current_manifest.variants
    ]
    bundles = [
        ObservedBundle(
            observed_ref=bundle_refs[bundle.id],
            variant_ref=variant_refs[bundle.variant_id],
            asset_refs=asset_refs_by_bundle.get(bundle.id, []),
        )
        for bundle in oracle_fixture.current_manifest.bundles
    ]
    return ObservedState(
        schema_version=2,
        consumer=ObservedConsumer(name="voom-v2", version="0.9.0"),
        run_id=run_id or oracle_fixture.run_id,
        observed_at=oracle_fixture.sentinel.created_at or datetime(2026, 5, 22, tzinfo=UTC),
        assets=assets,
        movies=movies if include_topology else [],
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
