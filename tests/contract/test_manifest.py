"""Tests for the manifest schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import chaos_librarian.contract.manifest as manifest_module
from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.domain import ParentKind
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


def _corruption_record() -> CorruptionRecord:
    return CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id="corrupt_header_001",
        corruptor="container_header_v1",
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:42:corrupt_header_001:asset_main",
    )


def _empty_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )


def test_empty_manifest_roundtrip() -> None:
    m = _empty_manifest()
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded == m


def test_populated_manifest_roundtrip() -> None:
    m = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="movie_orbit", title="Orbit", layout="movie_folder")],
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
                id="episode_special_01",
                season_id="season_specials",
                episode_number=1,
                title="First Signal",
                aired_on=None,
                absolute_number=None,
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
            )
        ],
        bundles=[ManifestBundle(id="bundle_movie", variant_id="variant_movie")],
        assets=[
            ManifestAsset(
                id="a1",
                bundle_id="bundle_movie",
                role="primary_video",
                container="mkv",
                duration_seconds=12,
            )
        ],
        versions=[ManifestVersion(id="ver1", asset_id="a1", index=0)],
        locations=[ManifestLocation(id="loc1", asset_id="a1", path="movies-hd/A.mkv")],
        sidecars=[],
    )
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded == m


def test_manifest_contract_removes_manifest_work() -> None:
    assert not hasattr(manifest_module, "ManifestWork")


def test_rejects_unknown_schema_version() -> None:
    bad = _empty_manifest().model_dump(mode="json")
    bad["schema_version"] = 999
    with pytest.raises(ValidationError):
        Manifest.model_validate(bad)


def test_probed_stream_video_only_fields():
    """WHY: Stream subtype fields (width/height/fps for video, channels for
    audio, default/forced for subtitle) must coexist on one model so the
    same `streams[]` array can hold heterogeneous entries from ffprobe."""
    stream = ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=1920, height=1080, fps=24.0)
    assert stream.channels is None
    assert stream.sample_rate is None


def test_probed_stream_audio_role_metadata_fields() -> None:
    stream = ProbedStream(
        kind=StreamKind.AUDIO,
        codec="aac",
        channels=3,
        sample_rate=48000,
        channel_layout="3.0",
        title="Commentary",
        role="commentary",
    )

    assert stream.channel_layout == "3.0"
    assert stream.title == "Commentary"
    assert stream.role == "commentary"


def test_probed_media_round_trip():
    media = ProbedMedia(
        container="matroska,webm",
        duration_seconds=2.0,
        size_bytes=12345,
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480, fps=24.0),
            ProbedStream(kind=StreamKind.AUDIO, codec="aac", channels=2, sample_rate=48000),
        ],
    )
    payload = media.model_dump_json(exclude_none=True)
    loaded = ProbedMedia.model_validate_json(payload)
    assert loaded == media


def test_manifest_version_probed_defaults_none():
    """WHY: plan-only manifests must stay bit-identical post-v2 bump.
    The default None plus exclude_none=True in the writer guarantees that."""
    version = ManifestVersion(id="v0", asset_id="a0", index=0)
    payload = version.model_dump(exclude_none=True)
    assert "probed" not in payload
    assert "content_hash" not in payload


def test_manifest_sidecar_content_hash_optional():
    sidecar = ManifestSidecar(
        id="s0",
        asset_id="a0",
        kind="subtitle",
        path="library/a/0.eng.srt",
        language="eng",
    )
    assert sidecar.content_hash is None
    payload = sidecar.model_dump(exclude_none=True)
    assert "content_hash" not in payload


def test_manifest_schema_version_is_eight():
    assert MANIFEST_SCHEMA_VERSION == 8


def test_manifest_sidecar_poster_no_language():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="poster",
        path="asset_main.poster.png",
        language=None,
    )
    assert sidecar.language is None
    assert sidecar.kind == "poster"


def test_manifest_sidecar_nfo_no_language():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="nfo",
        path="asset_main.nfo",
        language=None,
    )
    assert sidecar.language is None
    assert sidecar.kind == "nfo"


def test_manifest_sidecar_subtitle_keeps_language():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="subtitle",
        path="asset_main.eng.srt",
        language="eng",
    )
    assert sidecar.language == "eng"
    assert sidecar.kind == "subtitle"


def test_manifest_sidecar_kind_remains_free_form():
    sidecar = ManifestSidecar.model_validate(
        {
            "id": "sidecar_0001",
            "asset_id": "asset_main",
            "kind": "srt",
            "path": "asset_main.eng.srt",
            "language": "eng",
        }
    )
    assert sidecar.kind == "srt"


def test_manifest_v8_schema_version():
    manifest = Manifest(
        schema_version=8,
        movies=[],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )
    assert manifest.schema_version == 8


def test_manifest_version_round_trips_corruption_metadata() -> None:
    version = ManifestVersion(
        id="version_0002",
        asset_id="asset_main",
        index=1,
        corruption=_corruption_record(),
    )

    loaded = ManifestVersion.model_validate_json(version.model_dump_json())

    assert loaded == version
    assert loaded.corruption is not None
    assert loaded.corruption.profile is ProfileName.MALFORMED_MEDIA


def test_manifest_poster_sidecar_json_round_trip():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="poster",
        path="asset_main.poster.png",
        language=None,
    )
    payload = sidecar.model_dump_json()
    restored = ManifestSidecar.model_validate_json(payload)
    assert restored == sidecar
    assert restored.language is None
