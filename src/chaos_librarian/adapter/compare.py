"""Adapter comparison orchestration."""

from __future__ import annotations

from chaos_librarian.adapter.errors import E_ADAPTER_RUN_ID_MISMATCH, AdapterInputError
from chaos_librarian.adapter.fixture import OracleFixture
from chaos_librarian.adapter.history import compare_identity_history
from chaos_librarian.adapter.index import (
    ObservedAssetView,
    ObservedIndex,
    OracleAssetView,
    OracleIndex,
    topology_key,
)
from chaos_librarian.adapter.matching import AssetMatch, match_assets
from chaos_librarian.adapter.probe import compare_probed_media
from chaos_librarian.contract.divergence import (
    CompareMode,
    DivergenceCode,
    DivergenceFinding,
    DivergenceFixtureMetadata,
    DivergenceObservedMetadata,
    DivergenceReport,
    DivergenceSeverity,
)
from chaos_librarian.contract.manifest import ManifestSidecar
from chaos_librarian.contract.observed_state import ObservedSidecar, ObservedState


def compare_fixture_to_observed(
    fixture: OracleFixture,
    observed: ObservedState,
    *,
    mode: CompareMode = CompareMode.FINAL_STATE,
) -> DivergenceReport:
    """Compare an oracle fixture with a consumer observed-state export."""
    if fixture.run_id != observed.run_id:
        raise AdapterInputError(
            error_code=E_ADAPTER_RUN_ID_MISMATCH,
            message="observed run_id does not match oracle fixture run_id",
            details={
                "fixture_run_id": str(fixture.run_id),
                "observed_run_id": str(observed.run_id),
            },
        )

    oracle_index = OracleIndex.from_fixture(fixture)
    observed_index = ObservedIndex.from_state(observed)
    match_result = match_assets(oracle_index, observed_index)
    findings = list(match_result.findings)
    for match in match_result.matches:
        oracle_asset = oracle_index.assets[match.oracle_asset_id]
        observed_asset = observed_index.assets[match.observed_ref]
        findings.extend(_compare_matched_asset(match, oracle_asset, observed_asset))
        findings.extend(_compare_sidecars(match, oracle_asset, observed_asset))
        findings.extend(_compare_topology(match, oracle_index, observed_index))
    if mode is CompareMode.IDENTITY_HISTORY:
        findings.extend(compare_identity_history(match_result, oracle_index, observed_index))

    has_error = any(finding.severity is DivergenceSeverity.ERROR for finding in findings)
    return DivergenceReport(
        schema_version=1,
        run_id=fixture.run_id,
        mode=mode,
        ok=not has_error,
        fixture=DivergenceFixtureMetadata(
            run_dir=str(fixture.run_dir),
            execution_mode=fixture.replay_bundle.execution_mode.value,
            asset_count=len(fixture.current_manifest.assets),
            journal_entries=len(fixture.journal),
        ),
        observed=DivergenceObservedMetadata(
            consumer_name=observed.consumer.name,
            consumer_version=observed.consumer.version,
            observed_at=observed.observed_at,
            asset_count=len(observed.assets),
        ),
        findings=findings,
    )


def _compare_matched_asset(
    match: AssetMatch,
    oracle_asset: OracleAssetView,
    observed_asset: ObservedAssetView,
) -> list[DivergenceFinding]:
    findings: list[DivergenceFinding] = []
    findings.extend(_compare_paths(match, oracle_asset, observed_asset))
    findings.extend(_compare_hashes(match, oracle_asset, observed_asset))
    findings.extend(_compare_probes(match, oracle_asset, observed_asset))
    return findings


def _compare_paths(
    match: AssetMatch,
    oracle_asset: OracleAssetView,
    observed_asset: ObservedAssetView,
) -> list[DivergenceFinding]:
    if (oracle_asset.current_path is None) != (observed_asset.current_path is None):
        return [
            _finding(
                DivergenceCode.DELETION_MISMATCH,
                "Deletion state differs for matched asset.",
                match=match,
                expected={"current_path": oracle_asset.current_path},
                observed={"current_path": observed_asset.current_path},
            )
        ]
    if oracle_asset.current_path != observed_asset.current_path:
        return [
            _finding(
                DivergenceCode.PATH_MISMATCH,
                "Current path differs for matched asset.",
                match=match,
                expected={"current_path": oracle_asset.current_path},
                observed={"current_path": observed_asset.current_path},
            )
        ]
    return []


def _compare_hashes(
    match: AssetMatch,
    oracle_asset: OracleAssetView,
    observed_asset: ObservedAssetView,
) -> list[DivergenceFinding]:
    if oracle_asset.content_hash is None or observed_asset.content_hash is None:
        return []
    if oracle_asset.content_hash == observed_asset.content_hash:
        return []
    return [
        _finding(
            DivergenceCode.HASH_MISMATCH,
            "Content hash differs for matched asset.",
            match=match,
            expected={"content_hash": oracle_asset.content_hash},
            observed={"content_hash": observed_asset.content_hash},
        )
    ]


def _compare_probes(
    match: AssetMatch,
    oracle_asset: OracleAssetView,
    observed_asset: ObservedAssetView,
) -> list[DivergenceFinding]:
    if oracle_asset.probed is None or observed_asset.probed is None:
        return []
    differences = compare_probed_media(oracle_asset.probed, observed_asset.probed)
    if not differences:
        return []
    expected = {field: expected_value for field, expected_value, _ in differences}
    actual = {field: observed_value for field, _, observed_value in differences}
    return [
        _finding(
            DivergenceCode.PROBE_MISMATCH,
            "Probed media differs for matched asset.",
            match=match,
            expected=expected,
            observed=actual,
        )
    ]


def _compare_sidecars(
    match: AssetMatch,
    oracle_asset: OracleAssetView,
    observed_asset: ObservedAssetView,
) -> list[DivergenceFinding]:
    findings: list[DivergenceFinding] = []
    oracle_by_key = {_sidecar_key(sidecar): sidecar for sidecar in oracle_asset.sidecars}
    observed_by_key = {_sidecar_key(sidecar): sidecar for sidecar in observed_asset.sidecars}
    for key in sorted(set(oracle_by_key) - set(observed_by_key)):
        findings.append(_missing_sidecar(match, oracle_by_key[key]))
    for key in sorted(set(observed_by_key) - set(oracle_by_key)):
        findings.append(_unexpected_sidecar(match, observed_by_key[key]))
    for key in sorted(set(oracle_by_key) & set(observed_by_key)):
        oracle_sidecar = oracle_by_key[key]
        observed_sidecar = observed_by_key[key]
        if _sidecar_hashes_differ(oracle_sidecar, observed_sidecar):
            findings.append(_sidecar_hash_mismatch(match, oracle_sidecar, observed_sidecar))
    return findings


def _compare_topology(
    match: AssetMatch, oracle_index: OracleIndex, observed_index: ObservedIndex
) -> list[DivergenceFinding]:
    oracle_topology = oracle_index.topology.get(match.oracle_asset_id)
    observed_topology = observed_index.topology.get(match.observed_ref)
    if oracle_topology is None or observed_topology is None:
        return []
    oracle_key = topology_key(
        parent_kind=oracle_topology.parent_kind,
        variant_label=oracle_topology.variant_label,
        bundle_member_count=len(oracle_topology.bundle_asset_ids),
        movie_title=oracle_topology.movie_title,
        series_title=oracle_topology.series_title,
        season_number=oracle_topology.season_number,
        episode_number=oracle_topology.episode_number,
        episode_title=oracle_topology.episode_title,
        artist_name=oracle_topology.artist_name,
        album_title=oracle_topology.album_title,
        disc_number=oracle_topology.disc_number,
        track_number=oracle_topology.track_number,
        track_title=oracle_topology.track_title,
    )
    observed_key = topology_key(
        parent_kind=observed_topology.parent_kind,
        variant_label=observed_topology.variant_label,
        bundle_member_count=len(observed_topology.bundle_asset_refs),
        movie_title=observed_topology.movie_title,
        series_title=observed_topology.series_title,
        season_number=observed_topology.season_number,
        episode_number=observed_topology.episode_number,
        episode_title=observed_topology.episode_title,
        artist_name=observed_topology.artist_name,
        album_title=observed_topology.album_title,
        disc_number=observed_topology.disc_number,
        track_number=observed_topology.track_number,
        track_title=observed_topology.track_title,
    )
    if oracle_key is None or observed_key is None or oracle_key == observed_key:
        return []
    return [
        _finding(
            DivergenceCode.TOPOLOGY_MISMATCH,
            "Topology relationship structure differs for matched asset.",
            match=match,
            expected={
                "parent_kind": oracle_topology.parent_kind.value,
                "domain_key": oracle_key,
            },
            observed={
                "parent_kind": (
                    observed_topology.parent_kind.value
                    if observed_topology.parent_kind is not None
                    else None
                ),
                "domain_key": observed_key,
            },
        )
    ]


def _sidecar_key(sidecar: ManifestSidecar | ObservedSidecar) -> tuple[str, str]:
    return sidecar.path, sidecar.kind


def _sidecar_hashes_differ(
    oracle_sidecar: ManifestSidecar, observed_sidecar: ObservedSidecar
) -> bool:
    if oracle_sidecar.content_hash is None or observed_sidecar.content_hash is None:
        return False
    return oracle_sidecar.content_hash != observed_sidecar.content_hash


def _missing_sidecar(match: AssetMatch, sidecar: ManifestSidecar) -> DivergenceFinding:
    return _finding(
        DivergenceCode.SIDECAR_MISSING,
        "Oracle sidecar is missing from observed asset.",
        match=match,
        expected=_sidecar_payload(sidecar),
        observed=None,
    )


def _unexpected_sidecar(match: AssetMatch, sidecar: ObservedSidecar) -> DivergenceFinding:
    return _finding(
        DivergenceCode.SIDECAR_UNEXPECTED,
        "Observed sidecar is not present in oracle asset.",
        match=match,
        expected=None,
        observed=_sidecar_payload(sidecar),
        observed_ref=sidecar.observed_ref,
    )


def _sidecar_hash_mismatch(
    match: AssetMatch, oracle_sidecar: ManifestSidecar, observed_sidecar: ObservedSidecar
) -> DivergenceFinding:
    return _finding(
        DivergenceCode.HASH_MISMATCH,
        "Sidecar content hash differs for matched asset.",
        match=match,
        expected=_sidecar_payload(oracle_sidecar),
        observed=_sidecar_payload(observed_sidecar),
        observed_ref=observed_sidecar.observed_ref,
    )


def _sidecar_payload(sidecar: ManifestSidecar | ObservedSidecar) -> dict[str, object | None]:
    return {
        "path": sidecar.path,
        "kind": sidecar.kind,
        "content_hash": sidecar.content_hash,
    }


def _finding(
    code: DivergenceCode,
    message: str,
    *,
    match: AssetMatch,
    expected: object | None,
    observed: object | None,
    observed_ref: str | None = None,
) -> DivergenceFinding:
    return DivergenceFinding(
        code=code,
        severity=DivergenceSeverity.ERROR,
        message=message,
        oracle_asset_id=match.oracle_asset_id,
        observed_ref=observed_ref or match.observed_ref,
        expected=expected,
        observed=observed,
        evidence=list(match.evidence),
    )
