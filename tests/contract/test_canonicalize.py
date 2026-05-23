"""Layer 4 sibling — canonicalize() strips volatile fields without losing
structural ones."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from chaos_librarian.contract.canonicalize import canonicalize, corruption_evidence
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
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    MaterializationReport,
    Outcome,
    ToolchainInfo,
)
from chaos_librarian.contract.profiles import (
    CorruptionProbeOutcome,
    CorruptionRecord,
    ProfileName,
)
from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName


def _manifest(
    *,
    content_hash: str | None,
    probed: ProbedMedia | None,
    corrupted: bool = False,
) -> Manifest:
    return Manifest(
        schema_version=5,
        works=[ManifestWork(id="w0", title="Title")],
        variants=[ManifestVariant(id="va0", work_id="w0", label="hd")],
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
    structural shape (works/variants/bundles/assets/versions/locations/
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
    assert [w["id"] for w in out["works"]] == ["w0"]
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
) -> MaterializationReport:
    return MaterializationReport(
        schema_version=6,
        run_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        outcome=Outcome.SUCCESS,
        platform="test",
        started_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 21, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
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
                byte_start=0,
                byte_count=64,
                seed_material="container_header_v1:7:corrupt_header_001:a0",
                probe_outcome=probe_outcome,
                probe_error_tail="volatile probe stderr",
                duration_ns=123,
            )
        ],
    )
