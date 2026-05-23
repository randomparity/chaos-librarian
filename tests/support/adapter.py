"""Shared adapter test fixtures."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.adapter.fixture import OracleFixture, OracleReports
from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
    ProbedMedia,
    ProbedStream,
    StreamKind,
)
from chaos_librarian.contract.observed_state import (
    ObservedAsset,
    ObservedBundle,
    ObservedConsumer,
    ObservedSidecar,
    ObservedState,
    ObservedVariant,
    ObservedWork,
)
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.contract.reports import (
    AssetReport,
    AssetSnapshot,
    BundleReport,
    VariantReport,
    WorkReport,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine import run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

RUN_ID = uuid.UUID("7c44eb62-7046-4b8f-a168-eaf3a58e0145")
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def scenario_bytes(name: str) -> bytes:
    return (Path("tests/fixtures/scenarios") / name).read_bytes()


def write_plan_fixture(tmp_path: Path, scenario_name: str = "identity-move-rename.yaml") -> Path:
    scenario_yaml_bytes = scenario_bytes(scenario_name)
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_yaml_bytes,
        source_label=f"test:{scenario_name}",
    )
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)
    run_dir = tmp_path / "run"
    write_fixture(run_dir, artifacts, scenario_yaml_bytes)
    return run_dir


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
        works=[ManifestWork(id="work-a", title="Synthetic")],
        variants=[ManifestVariant(id="variant-a", work_id="work-a", label="hd")],
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
                initial=initial_snapshot,
                history=[],
                current=current_snapshot,
            )
        },
        works={
            "work-a": WorkReport(
                schema_version=1,
                work_id="work-a",
                title="Synthetic",
                variant_ids=["variant-a"],
                asset_ids=["asset-a"],
            )
        },
        variants={
            "variant-a": VariantReport(
                schema_version=1,
                variant_id="variant-a",
                work_id="work-a",
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
        schema_version=1,
        consumer=ObservedConsumer(name="voom-v2", version="0.9.0"),
        run_id=run_id,
        observed_at=datetime(2026, 5, 22, tzinfo=UTC),
        assets=[
            ObservedAsset(
                observed_ref="observed-a",
                current_path=current_path,
                content_hash=content_hash,
                probed=probed,
                work_ref="consumer-work",
                variant_ref="consumer-variant",
                bundle_ref="consumer-bundle",
                sidecars=list(sidecars),
            )
        ],
        works=[ObservedWork(observed_ref="consumer-work", title="Synthetic")],
        variants=[
            ObservedVariant(
                observed_ref="consumer-variant",
                work_ref="consumer-work",
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
) -> ObservedState:
    locations = {
        location.asset_id: location for location in oracle_fixture.current_manifest.locations
    }
    versions = {version.asset_id: version for version in oracle_fixture.current_manifest.versions}
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
        current_path = location.path if location is not None else None
        if path_override is not None and not assets:
            current_path = path_override
        assets.append(
            ObservedAsset(
                observed_ref=f"observed-{asset.id}",
                current_path=current_path,
                content_hash=version.content_hash if version is not None else None,
                probed=version.probed if version is not None else None,
                sidecars=sidecars_by_asset.get(asset.id, []),
            )
        )
    return ObservedState(
        schema_version=1,
        consumer=ObservedConsumer(name="voom-v2", version="0.9.0"),
        run_id=run_id or oracle_fixture.run_id,
        observed_at=oracle_fixture.sentinel.created_at or datetime(2026, 5, 22, tzinfo=UTC),
        assets=assets,
    )
