"""Layer 4 sibling — canonicalize() strips volatile fields without losing
structural ones."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION, MATERIALIZATION_SCHEMA_VERSION
from chaos_librarian.contract.canonicalize import canonicalize, corruption_evidence
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.domain import ParentKind
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
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FilesystemAction,
    MaterializationReport,
    NetworkLagAction,
    OracleHashAction,
    Outcome,
    ToolchainInfo,
)
from chaos_librarian.contract.profiles import (
    CorruptionProbeOutcome,
    CorruptionRecord,
    ProfileName,
)
from chaos_librarian.contract.scenario import NetworkLagEffect, SidecarKind, TimelineActionName


def _manifest(
    *,
    content_hash: str | None,
    probed: ProbedMedia | None,
    corrupted: bool = False,
) -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="movie_0", title="Title", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="va0",
                parent_kind=ParentKind.MOVIE,
                parent_id="movie_0",
                label="hd",
            )
        ],
        bundles=[ManifestBundle(id="b0", variant_id="va0")],
        assets=[
            ManifestAsset(
                id="a0", bundle_id="b0", role="main", container="mkv", duration_seconds=2.0
            )
        ],
        versions=[
            ManifestVersion(
                id="v0",
                asset_id="a0",
                index=0,
                content_hash=content_hash,
                probed=probed,
                corruption=_corruption_record() if corrupted else None,
            )
        ],
        locations=[ManifestLocation(id="l0", asset_id="a0", path="library/w0/va0/main.mkv")],
        sidecars=[
            ManifestSidecar(
                id="s0",
                asset_id="a0",
                kind=SidecarKind.SUBTITLE,
                path="library/w0/va0/main.eng.srt",
                language="eng",
                content_hash="sha256:" + "f" * 64,
            )
        ],
    )


def test_canonicalize_strips_content_hash_and_probed():
    """WHY: cross-toolchain hash comparison is meaningless; only the
    structural shape (movies/variants/bundles/assets/versions/locations/
    sidecars + their ids and paths) is comparable."""
    left = _manifest(
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
    right = _manifest(content_hash=None, probed=None)
    assert canonicalize(left) == canonicalize(right)


def test_canonicalize_preserves_structural_fields():
    """WHY: a too-aggressive strip would make every manifest compare equal."""
    m = _manifest(content_hash=None, probed=None)
    out = canonicalize(m)
    assert [movie["id"] for movie in out["movies"]] == ["movie_0"]
    assert out["assets"][0]["container"] == "mkv"
    assert out["locations"][0]["path"] == "library/w0/va0/main.mkv"
    assert out["sidecars"][0]["path"] == "library/w0/va0/main.eng.srt"


def test_canonicalize_strips_sidecar_content_hash():
    """WHY: sidecar bytes also differ across toolchains (subtle UTF-8 BOM
    handling, newline conventions); the structural sidecar entry stays."""
    m = _manifest(content_hash=None, probed=None)
    out = canonicalize(m)
    assert "content_hash" not in out["sidecars"][0]


def test_cross_toolchain_corruption_evidence_ignores_probe_and_hash_drift():
    left_manifest = _manifest(
        content_hash="sha256:" + "0" * 64,
        probed=ProbedMedia(
            container="matroska,webm",
            duration_seconds=2.0,
            size_bytes=12345,
            streams=[
                ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480, fps=24.0)
            ],
        ),
        corrupted=True,
    )
    right_manifest = _manifest(
        content_hash="sha256:" + "9" * 64,
        probed=ProbedMedia(
            container="matroska",
            duration_seconds=2.1,
            size_bytes=54321,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1280, height=720)],
        ),
        corrupted=True,
    )

    left = corruption_evidence(
        left_manifest,
        _report(
            input_hash="sha256:" + "1" * 64,
            output_hash="sha256:" + "2" * 64,
            probe_outcome=CorruptionProbeOutcome.FAILED_EXPECTED,
        ),
    )
    right = corruption_evidence(
        right_manifest,
        _report(
            input_hash="sha256:" + "3" * 64,
            output_hash="sha256:" + "4" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
        ),
    )

    assert left == right


def test_oracle_hash_evidence_ignores_actual_and_reported_hash_drift() -> None:
    left = corruption_evidence(
        _manifest(content_hash=None, probed=None),
        _report(
            input_hash="sha256:" + "1" * 64,
            output_hash="sha256:" + "2" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
            oracle_hash_actions=[
                _oracle_hash_action(
                    actual_hash="sha256:" + "3" * 64,
                    reported_hash="sha256:" + "4" * 64,
                )
            ],
        ),
    )
    right = corruption_evidence(
        _manifest(content_hash=None, probed=None),
        _report(
            input_hash="sha256:" + "5" * 64,
            output_hash="sha256:" + "6" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
            oracle_hash_actions=[
                _oracle_hash_action(
                    actual_hash="sha256:" + "7" * 64,
                    reported_hash="sha256:" + "8" * 64,
                )
            ],
        ),
    )

    assert left == right
    evidence = left["oracle_hash_actions"][0]
    assert "actual_content_hash" not in evidence
    assert "reported_content_hash" not in evidence


def test_touch_mtime_evidence_preserves_delta_without_volatile_metadata() -> None:
    left = corruption_evidence(
        _manifest(content_hash=None, probed=None),
        _report(
            input_hash="sha256:" + "1" * 64,
            output_hash="sha256:" + "2" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
            filesystem_actions=[
                _touch_mtime_action(
                    content_hash="sha256:" + "3" * 64,
                    before_ns=1_000,
                    after_ns=3_500,
                )
            ],
        ),
    )
    right = corruption_evidence(
        _manifest(content_hash=None, probed=None),
        _report(
            input_hash="sha256:" + "4" * 64,
            output_hash="sha256:" + "5" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
            filesystem_actions=[
                _touch_mtime_action(
                    content_hash="sha256:" + "6" * 64,
                    before_ns=10_000,
                    after_ns=12_500,
                )
            ],
        ),
    )

    assert left == right
    evidence = left["filesystem_metadata_actions"][0]
    assert evidence["mtime_delta_ns"] == 2_500
    assert "content_hash" not in evidence
    assert "mtime_before_ns" not in evidence
    assert "mtime_after_ns" not in evidence


def test_network_lag_evidence_ignores_actual_duration_drift() -> None:
    left = corruption_evidence(
        _manifest(content_hash=None, probed=None),
        _report(
            input_hash="sha256:" + "1" * 64,
            output_hash="sha256:" + "2" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
            network_lag_actions=[_network_lag_action(actual_duration_ns=10)],
        ),
    )
    right = corruption_evidence(
        _manifest(content_hash=None, probed=None),
        _report(
            input_hash="sha256:" + "3" * 64,
            output_hash="sha256:" + "4" * 64,
            probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
            network_lag_actions=[_network_lag_action(actual_duration_ns=20)],
        ),
    )

    assert left == right
    evidence = left["network_lag_actions"][0]
    assert "actual_duration_ns" not in evidence


def _corruption_record() -> CorruptionRecord:
    return CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id="corrupt_header_001",
        corruptor="container_header_v1",
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:7:corrupt_header_001:a0",
    )


def _report(
    *,
    input_hash: str,
    output_hash: str,
    probe_outcome: CorruptionProbeOutcome,
    filesystem_actions: list[FilesystemAction] | None = None,
    oracle_hash_actions: list[OracleHashAction] | None = None,
    network_lag_actions: list[NetworkLagAction] | None = None,
) -> MaterializationReport:
    return MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        outcome=Outcome.SUCCESS,
        platform="test",
        started_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 21, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        content_sources=[
            ContentSourceEvidence(
                asset_id="a0",
                track_kind=ContentTrackKind.VIDEO,
                track_index=None,
                source="color_bars",
                provider="builtin-lavfi",
                recipe_digest="sha256:" + "0" * 64,
                cache_disposition=CacheDisposition.NOT_CACHEABLE,
                cache_key=None,
                content_hash=None,
                origin_uri=None,
                license=None,
            )
        ],
        corruption_actions=[
            CorruptionAction(
                event_id="corrupt_header_001",
                action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
                target_asset_id="a0",
                input_path="library/a0.mkv",
                output_path="library/a0.mkv",
                input_version_id="v0",
                output_version_id="v1",
                input_content_hash=input_hash,
                output_content_hash=output_hash,
                corruptor="container_header_v1",
                input_size_bytes=128,
                output_size_bytes=128,
                byte_start=0,
                byte_count=64,
                seed_material="container_header_v1:7:corrupt_header_001:a0",
                probe_outcome=probe_outcome,
                probe_error_tail="volatile probe stderr",
                duration_ns=123,
            )
        ],
        filesystem_actions=filesystem_actions or [],
        oracle_hash_actions=oracle_hash_actions or [],
        network_lag_actions=network_lag_actions or [],
    )


def _oracle_hash_action(*, actual_hash: str, reported_hash: str) -> OracleHashAction:
    return OracleHashAction(
        event_id="wrong_hash_001",
        action=TimelineActionName.WRONG_ORACLE_HASH,
        target_asset_id="a0",
        input_path="library/a0.mkv",
        output_path="library/a0.mkv",
        input_version_id="v0",
        output_version_id="v1",
        actual_content_hash=actual_hash,
        reported_content_hash=reported_hash,
        seed_material="wrong_oracle_hash_v1:7:wrong_hash_001:a0",
        duration_ns=123,
    )


def _touch_mtime_action(
    *,
    content_hash: str,
    before_ns: int,
    after_ns: int,
) -> FilesystemAction:
    return FilesystemAction(
        event_id="mtime_001",
        action=TimelineActionName.TOUCH_MTIME,
        target_asset_id="a0",
        from_path="library/a0.mkv",
        to_path="library/a0.mkv",
        content_hash=content_hash,
        mtime_before_ns=before_ns,
        mtime_after_ns=after_ns,
        duration_ns=123,
    )


def _network_lag_action(*, actual_duration_ns: int) -> NetworkLagAction:
    return NetworkLagAction(
        event_id="lag_start_001",
        commit_event_id="lag_commit_001",
        effect=NetworkLagEffect.DELAYED_RENAME,
        target_ref="a0",
        after_event_id="rename_001",
        logical_start_ns=1,
        logical_commit_ns=2,
        requested_duration_ns=1,
        actual_duration_ns=actual_duration_ns,
        from_path="library/a0.mkv",
        to_path="library/a0-renamed.mkv",
        provider="stdlib-local",
        enforced=True,
    )
