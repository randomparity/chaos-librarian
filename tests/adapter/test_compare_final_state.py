"""Tests for final-state adapter comparison."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import cast

import pytest

from chaos_librarian.adapter.compare import compare_fixture_to_observed
from chaos_librarian.adapter.errors import E_ADAPTER_RUN_ID_MISMATCH, AdapterInputError
from chaos_librarian.contract.divergence import CompareMode, DivergenceCode
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import (
    ManifestEpisode,
    ManifestSeason,
    ManifestSeries,
    ManifestSidecar,
    ManifestVariant,
    ProbedMedia,
    ProbedStream,
    StreamKind,
)
from chaos_librarian.contract.observed_state import ObservedSidecar, ObservedState
from chaos_librarian.contract.scenario import SidecarKind
from tests.support.adapter import (
    HASH_A,
    HASH_B,
)
from tests.support.adapter import (
    fixture as _fixture,
)
from tests.support.adapter import (
    observed as _observed,
)
from tests.support.adapter import (
    observed_from_fixture as _observed_from_fixture,
)
from tests.support.adapter import (
    probe as _probe,
)


def _codes(report) -> list[str]:
    return [finding.code for finding in report.findings]


def _observed_episode_topology() -> ObservedState:
    payload = _observed().model_dump(mode="python")
    payload["movies"] = []
    payload["series"] = [{"observed_ref": "consumer-series", "title": "Synthetic"}]
    payload["seasons"] = [
        {
            "observed_ref": "consumer-season",
            "series_ref": "consumer-series",
            "season_number": 1,
            "title": "Season 1",
        }
    ]
    payload["episodes"] = [
        {
            "observed_ref": "consumer-episode",
            "season_ref": "consumer-season",
            "episode_number": 1,
            "title": "Synthetic",
        }
    ]
    payload["variants"][0]["parent_kind"] = ParentKind.EPISODE
    payload["variants"][0]["parent_ref"] = "consumer-episode"
    return ObservedState.model_validate(payload)


def _observed_episode_topology_with_extra_bundle_asset() -> ObservedState:
    payload = _observed_episode_topology().model_dump(mode="python")
    payload["assets"].append(
        {
            "observed_ref": "observed-extra",
            "current_path": "library/Extra.mkv",
            "content_hash": HASH_B,
            "variant_ref": "consumer-variant",
            "bundle_ref": "consumer-bundle",
        }
    )
    payload["bundles"][0]["asset_refs"] = ["observed-a", "observed-extra"]
    return ObservedState.model_validate(payload)


def _episode_manifest(manifest):
    return manifest.model_copy(
        update={
            "movies": [],
            "series": [
                ManifestSeries(
                    id="series-a",
                    title="Synthetic",
                    layout="series_flat",
                    episode_naming="sxe",
                )
            ],
            "seasons": [
                ManifestSeason(
                    id="season-a",
                    series_id="series-a",
                    season_number=1,
                    title="Season 1",
                )
            ],
            "episodes": [
                ManifestEpisode(
                    id="episode-a",
                    season_id="season-a",
                    episode_number=1,
                    title="Synthetic",
                )
            ],
            "variants": [
                ManifestVariant(
                    id="variant-a",
                    parent_kind=ParentKind.EPISODE,
                    parent_id="episode-a",
                    label="hd",
                )
            ],
        }
    )


def _episode_fixture():
    base = _fixture()
    manifest = _episode_manifest(base.initial_manifest)
    return replace(base, initial_manifest=manifest, current_manifest=manifest)


def _fixture_for_episode():
    return _fixture(parent_kind=ParentKind.EPISODE)


def _fixture_for_track():
    return _fixture(parent_kind=ParentKind.TRACK)


def _movie_to_episode_fixture():
    base = _fixture()
    return replace(base, current_manifest=_episode_manifest(base.current_manifest))


def test_clean_observed_state_returns_ok_report() -> None:
    report = compare_fixture_to_observed(_fixture(), _observed())

    assert report.ok is True
    assert report.findings == []
    assert report.fixture.asset_count == 1
    assert report.observed.consumer_name == "voom-v2"


def test_observed_from_fixture_emits_episode_domain_rows() -> None:
    fixture = _fixture_for_episode()

    observed = _observed_from_fixture(fixture, include_topology=True)

    assert observed.series[0].title == "Starline"
    assert observed.seasons[0].series_ref == "observed-series-a"
    assert observed.episodes[0].season_ref == "observed-season-a"
    assert observed.variants[0].parent_kind is ParentKind.EPISODE
    assert observed.variants[0].parent_ref == "observed-episode-a"


def test_observed_from_fixture_emits_track_domain_rows() -> None:
    fixture = _fixture_for_track()

    observed = _observed_from_fixture(fixture, include_topology=True)

    assert observed.artists[0].name == "North Index"
    assert observed.albums[0].artist_ref == "observed-artist-a"
    assert observed.discs[0].album_ref == "observed-album-a"
    assert observed.tracks[0].disc_ref == "observed-disc-a"
    assert observed.variants[0].parent_kind is ParentKind.TRACK
    assert observed.variants[0].parent_ref == "observed-track-a"


def test_episode_topology_from_fixture_compares_clean() -> None:
    fixture = _fixture_for_episode()
    observed = _observed_from_fixture(fixture, include_topology=True)

    report = compare_fixture_to_observed(fixture, observed)

    assert report.ok is True
    assert report.findings == []


def test_track_topology_from_fixture_compares_clean() -> None:
    fixture = _fixture_for_track()
    observed = _observed_from_fixture(fixture, include_topology=True)

    report = compare_fixture_to_observed(fixture, observed)

    assert report.ok is True
    assert report.findings == []


def test_run_id_mismatch_is_input_error_not_divergence() -> None:
    with pytest.raises(AdapterInputError) as exc_info:
        compare_fixture_to_observed(_fixture(), _observed(run_id=uuid.uuid4()))
    assert exc_info.value.error_code == E_ADAPTER_RUN_ID_MISMATCH


def test_path_mismatch_emits_d_path_mismatch() -> None:
    report = compare_fixture_to_observed(
        _fixture(),
        _observed(current_path="library/Different.mkv"),
    )

    assert "D_PATH_MISMATCH" in _codes(report)


def test_deletion_mismatch_emits_d_deletion_mismatch() -> None:
    report = compare_fixture_to_observed(
        _fixture(current_path=None),
        _observed(current_path="library/Synthetic.mkv"),
    )

    assert "D_DELETION_MISMATCH" in _codes(report)


def test_hash_mismatch_requires_both_hashes() -> None:
    with_hashes = compare_fixture_to_observed(_fixture(), _observed(content_hash=HASH_B))
    missing_hash = compare_fixture_to_observed(_fixture(), _observed(content_hash=None))

    assert "D_HASH_MISMATCH" in _codes(with_hashes)
    assert "D_HASH_MISMATCH" not in _codes(missing_hash)


def test_negative_oracle_hash_surfaces_hash_mismatch() -> None:
    report = compare_fixture_to_observed(
        _fixture(content_hash=HASH_B),
        _observed(content_hash=HASH_A),
    )

    assert report.ok is False
    assert report.findings[0].code is DivergenceCode.HASH_MISMATCH


def test_probe_mismatch_requires_both_probed_values() -> None:
    with_probes = compare_fixture_to_observed(
        _fixture(probed=_probe(codec="h264")),
        _observed(probed=_probe(codec="hevc")),
    )
    missing_probe = compare_fixture_to_observed(_fixture(probed=_probe()), _observed(probed=None))

    assert "D_PROBE_MISMATCH" in _codes(with_probes)
    assert "D_PROBE_MISMATCH" not in _codes(missing_probe)


def test_probe_duration_uses_point_zero_five_second_tolerance() -> None:
    tolerated = compare_fixture_to_observed(
        _fixture(probed=_probe(duration=60.0)),
        _observed(probed=_probe(duration=60.05)),
    )
    outside = compare_fixture_to_observed(
        _fixture(probed=_probe(duration=60.0)),
        _observed(probed=_probe(duration=60.051)),
    )

    assert "D_PROBE_MISMATCH" not in _codes(tolerated)
    assert "D_PROBE_MISMATCH" in _codes(outside)


def test_probe_unknown_language_equivalence_keeps_final_state_compare_clean() -> None:
    oracle_probe = ProbedMedia(
        container="mov,mp4,m4a,3gp,3g2,mj2",
        duration_seconds=60.0,
        size_bytes=12345,
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", language="und"),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", language="und"),
        ],
    )
    observed_probe = oracle_probe.model_copy(
        update={
            "streams": [
                ProbedStream(kind=StreamKind.VIDEO, codec="h264", language=None),
                ProbedStream(kind=StreamKind.AUDIO, codec="aac", language=None),
            ]
        }
    )

    report = compare_fixture_to_observed(
        _fixture(probed=oracle_probe),
        _observed(probed=observed_probe),
    )

    assert "D_PROBE_MISMATCH" not in _codes(report)


def test_missing_observed_sidecar_emits_d_sidecar_missing() -> None:
    sidecar = ManifestSidecar(
        id="sidecar-a",
        asset_id="asset-a",
        kind=SidecarKind.SUBTITLE,
        path="library/Synthetic.eng.srt",
        content_hash=HASH_A,
    )

    report = compare_fixture_to_observed(_fixture(sidecars=(sidecar,)), _observed())

    assert "D_SIDECAR_MISSING" in _codes(report)


def test_unexpected_observed_sidecar_emits_d_sidecar_unexpected() -> None:
    observed_sidecar = ObservedSidecar(
        observed_ref="observed-sidecar-a",
        kind=SidecarKind.SUBTITLE,
        path="library/Synthetic.eng.srt",
        content_hash=HASH_A,
    )

    report = compare_fixture_to_observed(_fixture(), _observed(sidecars=(observed_sidecar,)))

    assert "D_SIDECAR_UNEXPECTED" in _codes(report)


def test_sidecar_kind_mismatch_emits_missing_and_unexpected() -> None:
    oracle_sidecar = ManifestSidecar(
        id="sidecar-a",
        asset_id="asset-a",
        kind=SidecarKind.SUBTITLE,
        path="library/Synthetic.sidecar",
    )
    observed_sidecar = ObservedSidecar(
        observed_ref="observed-sidecar-a",
        kind="poster",
        path="library/Synthetic.sidecar",
    )

    report = compare_fixture_to_observed(
        _fixture(sidecars=(oracle_sidecar,)),
        _observed(sidecars=(observed_sidecar,)),
    )

    assert "D_SIDECAR_MISSING" in _codes(report)
    assert "D_SIDECAR_UNEXPECTED" in _codes(report)


def test_sidecar_hash_mismatch_emits_d_hash_mismatch() -> None:
    oracle_sidecar = ManifestSidecar(
        id="sidecar-a",
        asset_id="asset-a",
        kind=SidecarKind.SUBTITLE,
        path="library/Synthetic.eng.srt",
        content_hash=HASH_A,
    )
    observed_sidecar = ObservedSidecar(
        observed_ref="observed-sidecar-a",
        kind="subtitle",
        path="library/Synthetic.eng.srt",
        content_hash=HASH_B,
    )

    report = compare_fixture_to_observed(
        _fixture(sidecars=(oracle_sidecar,)),
        _observed(sidecars=(observed_sidecar,)),
    )

    assert "D_HASH_MISMATCH" in _codes(report)


def test_missing_observed_sidecar_hash_is_not_divergence() -> None:
    oracle_sidecar = ManifestSidecar(
        id="sidecar-a",
        asset_id="asset-a",
        kind=SidecarKind.SUBTITLE,
        path="library/Synthetic.eng.srt",
        content_hash=HASH_A,
    )
    observed_sidecar = ObservedSidecar(
        observed_ref="observed-sidecar-a",
        kind="subtitle",
        path="library/Synthetic.eng.srt",
        content_hash=None,
    )

    report = compare_fixture_to_observed(
        _fixture(sidecars=(oracle_sidecar,)),
        _observed(sidecars=(observed_sidecar,)),
    )

    assert "D_HASH_MISMATCH" not in _codes(report)


def test_topology_refs_can_differ_when_relationship_structure_matches() -> None:
    report = compare_fixture_to_observed(_fixture(), _observed())

    assert "D_TOPOLOGY_MISMATCH" not in _codes(report)


def test_topology_mismatch_emits_d_topology_mismatch_when_both_sides_supply_refs() -> None:
    report = compare_fixture_to_observed(_fixture(), _observed(topology_label="sd"))

    assert "D_TOPOLOGY_MISMATCH" in _codes(report)
    finding = next(
        finding for finding in report.findings if finding.code is DivergenceCode.TOPOLOGY_MISMATCH
    )
    assert isinstance(finding.expected, dict)
    assert isinstance(finding.observed, dict)
    expected = cast("dict[str, object]", finding.expected)
    observed = cast("dict[str, object]", finding.observed)
    assert expected["domain_key"] == "movie:Synthetic|hd|1"
    assert observed["domain_key"] == "movie:Synthetic|sd|1"


def test_topology_mismatch_includes_parent_kind_after_path_match() -> None:
    report = compare_fixture_to_observed(_fixture(), _observed_episode_topology())

    assert "D_TOPOLOGY_MISMATCH" in _codes(report)
    finding = next(
        finding for finding in report.findings if finding.code is DivergenceCode.TOPOLOGY_MISMATCH
    )
    assert isinstance(finding.expected, dict)
    assert isinstance(finding.observed, dict)
    expected = cast("dict[str, object]", finding.expected)
    observed = cast("dict[str, object]", finding.observed)
    assert expected["parent_kind"] == "movie"
    assert observed["parent_kind"] == "episode"
    assert expected["domain_key"] == "movie:Synthetic|hd|1"
    assert observed["domain_key"] == "episode:Synthetic|1|1|Synthetic|hd"


def test_compare_uses_current_manifest_topology_after_hierarchy_mutation() -> None:
    report = compare_fixture_to_observed(_movie_to_episode_fixture(), _observed_episode_topology())

    assert "D_TOPOLOGY_MISMATCH" not in _codes(report)


def test_compare_rejects_stale_observed_topology_after_hierarchy_mutation() -> None:
    report = compare_fixture_to_observed(_movie_to_episode_fixture(), _observed())

    assert "D_TOPOLOGY_MISMATCH" in _codes(report)
    finding = next(
        finding for finding in report.findings if finding.code is DivergenceCode.TOPOLOGY_MISMATCH
    )
    assert isinstance(finding.expected, dict)
    assert isinstance(finding.observed, dict)
    expected = cast("dict[str, object]", finding.expected)
    observed = cast("dict[str, object]", finding.observed)
    assert expected["parent_kind"] == "episode"
    assert observed["parent_kind"] == "movie"


def test_episode_topology_mismatch_includes_bundle_member_count_after_path_match() -> None:
    report = compare_fixture_to_observed(
        _episode_fixture(),
        _observed_episode_topology_with_extra_bundle_asset(),
    )

    assert "D_TOPOLOGY_MISMATCH" in _codes(report)
    finding = next(
        finding for finding in report.findings if finding.code is DivergenceCode.TOPOLOGY_MISMATCH
    )
    assert isinstance(finding.expected, dict)
    assert isinstance(finding.observed, dict)
    expected = cast("dict[str, object]", finding.expected)
    observed = cast("dict[str, object]", finding.observed)
    assert expected["domain_key"] == "episode:Synthetic|1|1|Synthetic|hd"
    assert observed["domain_key"] == "episode:Synthetic|1|1|Synthetic|hd"
    assert expected["bundle_member_count"] == 1
    assert observed["bundle_member_count"] == 2


def test_final_state_mode_skips_history_when_no_history_supplied() -> None:
    observed = _observed()
    observed.assets[0].path_history.clear()

    report = compare_fixture_to_observed(_fixture(), observed, mode=CompareMode.FINAL_STATE)

    assert "D_HISTORY_MISSING" not in _codes(report)
