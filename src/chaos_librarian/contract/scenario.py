"""Scenario schema: input YAML format for chaos-librarian.

Mirrors the example in docs/specs/chaos-librarian-design.md "Scenario Format".
Timeline events are a discriminated union on ``action``.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Annotated, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from chaos_librarian.contract.profiles import (
    FUZZ_LANES_BY_PROFILE,
    FuzzLaneName,
    FuzzProfileName,
    ProfileName,
)


class TimelineActionName(enum.StrEnum):
    """All valid ``action:`` values for a timeline event.

    This is the single source of truth: discriminator literals on the
    variant classes below, the JSONPath formatter in ``validation.codes``,
    and the per-action path-field map in ``validation.semantic`` all
    reference these members instead of bare strings.
    """

    MOVE_ASSET = "move_asset"
    RENAME_FILE = "rename_file"
    DELETE_FILE = "delete_file"
    ADD_FILE = "add_file"
    REENCODE_VIDEO = "reencode_video"
    REENCODE_AUDIO = "reencode_audio"
    CREATE_SIDECAR = "create_sidecar"
    SLOW_COPY_START = "slow_copy_start"
    SLOW_COPY_COMMIT = "slow_copy_commit"
    ARCHIVE_FILE = "archive_file"
    MOVE_BETWEEN_ROOTS = "move_between_roots"
    REMUX_CONTAINER = "remux_container"
    EDIT_METADATA = "edit_metadata"
    EMBED_SUBTITLE = "embed_subtitle"
    EXTRACT_SUBTITLE = "extract_subtitle"
    REMOVE_SIDECAR = "remove_sidecar"
    UPDATE_SIDECAR = "update_sidecar"
    CORRUPT_CONTAINER_HEADER = "corrupt_container_header"
    TRUNCATE_FILE = "truncate_file"
    CORRUPT_PACKET_RANGE = "corrupt_packet_range"
    WRITE_INVALID_DURATION_METADATA = "write_invalid_duration_metadata"
    TOUCH_MTIME = "touch_mtime"
    WRONG_ORACLE_HASH = "wrong_oracle_hash"
    NETWORK_LAG_START = "network_lag_start"
    NETWORK_LAG_COMMIT = "network_lag_commit"
    CHANGE_PERMISSIONS = "change_permissions"
    SIMULATE_QUOTA_EXCEEDED = "simulate_quota_exceeded"
    TOGGLE_READONLY = "toggle_readonly"
    SIMULATE_STALE_HANDLE = "simulate_stale_handle"
    UNMOUNT_PATH = "unmount_path"
    REMOUNT_PATH = "remount_path"
    ACQUIRE_LOCK = "acquire_lock"
    RELEASE_LOCK = "release_lock"
    RENUMBER_EPISODE = "renumber_episode"
    MOVE_EPISODE_TO_SEASON = "move_episode_to_season"
    RENAME_SEASON = "rename_season"
    RENUMBER_DISC = "renumber_disc"
    MOVE_TRACK_TO_DISC = "move_track_to_disc"
    SWAP_EPISODE_NUMBERS = "swap_episode_numbers"
    SWAP_DISC_NUMBERS = "swap_disc_numbers"
    SWAP_TRACK_NUMBERS = "swap_track_numbers"
    REPUBLISH_EPISODE = "republish_episode"
    MARK_EPISODE_STALE = "mark_episode_stale"


ALL_TIMELINE_ACTIONS: Final[frozenset[str]] = frozenset(TimelineActionName)

# republish_episode re-renders an episode's path like renumber_episode, so it
# joins the hierarchy set (path-history projection, lifecycle hierarchy branch,
# is_hierarchy_action). mark_episode_stale changes a recorded fact, not a path,
# so it stays out.
HIERARCHY_TIMELINE_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
        TimelineActionName.RENUMBER_DISC,
        TimelineActionName.MOVE_TRACK_TO_DISC,
        TimelineActionName.SWAP_EPISODE_NUMBERS,
        TimelineActionName.SWAP_DISC_NUMBERS,
        TimelineActionName.SWAP_TRACK_NUMBERS,
        TimelineActionName.REPUBLISH_EPISODE,
    }
)


class VideoSource(enum.StrEnum):
    """Synthesis recipe for the video stream of an asset."""

    MANDELBROT = "mandelbrot"
    COLOR_BARS = "color_bars"
    SOLID_COLOR = "solid_color"
    NOISE = "noise"  # reserved; validate rejects it until materialize supports it


class VideoVfrCadence(enum.StrEnum):
    """Supported variable-frame-rate cadence transitions."""

    TWENTY_FOUR_TO_THIRTY = "24_to_30"
    THIRTY_TO_SIXTY = "30_to_60"
    TWENTY_FOUR_THIRTY_SIXTY = "24_30_60"


_YAML_NUMERIC_VFR_24_30_60: Final = 243060


class VideoFieldOrder(enum.StrEnum):
    """Supported interlaced video field orders."""

    TOP_FIELD_FIRST = "top_field_first"
    BOTTOM_FIELD_FIRST = "bottom_field_first"


class VideoColorSpace(enum.StrEnum):
    """Supported SDR video color-space signaling values."""

    BT601 = "bt601"
    BT709 = "bt709"
    BT2020 = "bt2020"


class VideoColorRange(enum.StrEnum):
    """Supported video color-range signaling values."""

    LIMITED = "limited"
    FULL = "full"


class VideoHdrMode(enum.StrEnum):
    """Supported HDR video signaling modes."""

    HDR10 = "hdr10"
    HLG = "hlg"


class VideoResolutionSequence(enum.StrEnum):
    """Supported mid-stream video resolution transitions."""

    SD_TO_HD = "sd_to_hd"


class Mp4MoovPlacement(enum.StrEnum):
    """MP4 top-level moov atom placement requested at mux time."""

    MOOV_AT_START = "moov_at_start"
    MOOV_AT_END = "moov_at_end"


class MatroskaMuxingProfile(enum.StrEnum):
    """Matroska/WebM muxing profile for cue and cluster parser surfaces."""

    NO_CUES = "no_cues"
    DENSE_CUES = "dense_cues"
    SHORT_CLUSTERS = "short_clusters"


class CoverArtSource(enum.StrEnum):
    """Synthesis recipe for embedded cover art."""

    SOLID_COLOR = "solid_color"


class CoverArtImageFormat(enum.StrEnum):
    """Image format for embedded cover art."""

    PNG = "png"


class CoverArtResolution(enum.StrEnum):
    """Pixel geometry for embedded cover art."""

    SQUARE_320 = "square_320"


class SubtitleMode(enum.StrEnum):
    """How a subtitle track is delivered."""

    EMBEDDED = "embedded"
    SIDECAR = "sidecar"


class DurationScale(enum.StrEnum):
    """Scenario duration scale family."""

    SHORT = "short"
    NORMAL = "normal"
    LONG = "long"


class AudioSource(enum.StrEnum):
    """Synthesis recipe for an audio stream."""

    SINE = "sine"
    SILENCE = "silence"
    CHANNEL_TONES = "channel_tones"
    NOISE = "noise"


class AudioNoiseColor(enum.StrEnum):
    """Supported deterministic audio noise colors."""

    WHITE = "white"
    PINK = "pink"
    BROWN = "brown"


class AudioSampleFormat(enum.StrEnum):
    """Author-facing sample formats for probe-verifiable audio outputs."""

    S16 = "s16"
    S24 = "s24"
    FLT = "flt"


class AudioTrackRole(enum.StrEnum):
    """Author-facing role for an audio stream."""

    MAIN = "main"
    COMMENTARY = "commentary"
    ALTERNATE = "alternate"


class AudioChannelLayout(enum.StrEnum):
    """Supported author-facing audio channel layouts."""

    MONO = "mono"
    STEREO = "stereo"
    TWO_ONE = "2.1"
    FOUR_ZERO = "4.0"
    LCR = "lcr"
    FIVE_ONE = "5.1"
    SIX_ONE = "6.1"
    SEVEN_ONE = "7.1"


AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME: Final[dict[str, str]] = {
    AudioChannelLayout.MONO.value: "mono",
    AudioChannelLayout.STEREO.value: "stereo",
    AudioChannelLayout.TWO_ONE.value: "2.1",
    AudioChannelLayout.FOUR_ZERO.value: "4.0",
    AudioChannelLayout.LCR.value: "3.0",
    AudioChannelLayout.FIVE_ONE.value: "5.1",
    AudioChannelLayout.SIX_ONE.value: "6.1",
    AudioChannelLayout.SEVEN_ONE.value: "7.1",
}
AUDIO_CHANNEL_ORDER_BY_NAME: Final[dict[str, tuple[str, ...]]] = {
    AudioChannelLayout.MONO.value: ("FC",),
    AudioChannelLayout.STEREO.value: ("FL", "FR"),
    AudioChannelLayout.TWO_ONE.value: ("FL", "FR", "LFE"),
    AudioChannelLayout.FOUR_ZERO.value: ("FL", "FR", "FC", "BC"),
    AudioChannelLayout.LCR.value: ("FL", "FR", "FC"),
    AudioChannelLayout.FIVE_ONE.value: ("FL", "FR", "FC", "LFE", "BL", "BR"),
    AudioChannelLayout.SIX_ONE.value: ("FL", "FR", "FC", "LFE", "BC", "SL", "SR"),
    AudioChannelLayout.SEVEN_ONE.value: ("FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"),
}
AUDIO_CHANNEL_COUNTS_BY_NAME: Final[dict[str, int]] = {
    name: len(order) for name, order in AUDIO_CHANNEL_ORDER_BY_NAME.items()
}


class SubtitleSource(enum.StrEnum):
    """Synthesis recipe for a subtitle track."""

    GENERATED_SRT = "generated_srt"
    STYLED_ASS = "styled_ass"


class SubtitleCodec(enum.StrEnum):
    """Sidecar subtitle codec/format."""

    SRT = "srt"
    ASS = "ass"
    SSA = "ssa"


class SubtitleEncoding(enum.StrEnum):
    """Text encoding for generated sidecar subtitle bytes."""

    UTF8 = "utf8"
    UTF8_BOM = "utf8_bom"
    UTF16_LE = "utf16_le"
    ISO_8859_1 = "iso_8859_1"


class SubtitleTimingProfile(enum.StrEnum):
    """Timing profile for generated subtitle cues."""

    NORMAL = "normal"
    OVERLAP = "overlap"
    OUT_OF_RANGE = "out_of_range"


class SidecarKind(enum.StrEnum):
    """Kind of a sidecar — extends Sprint 6's subtitle-only assumption.

    Subtitle requires ``language``; poster, NFO, and CUE forbid it. CUE (#118)
    is an authored ``.cue`` index sheet — like NFO it accepts an inline ``body``.
    """

    SUBTITLE = "subtitle"
    POSTER = "poster"
    NFO = "nfo"
    CUE = "cue"


class SidecarMediaType(enum.StrEnum):
    """Synthesized media kind for a poster sidecar.

    ``image`` is the default PNG poster; ``video`` writes a small deterministic
    video at the poster path — the ``poster-is-video`` chaos.
    """

    IMAGE = "image"
    VIDEO = "video"


class PosterImageFormat(enum.StrEnum):
    """Image format for a poster/album-art sidecar (#118).

    Selects the ffmpeg encoder for the synthesized poster image. Distinct from
    ``CoverArtImageFormat`` (embedded mp4 cover art) so the standalone-sidecar
    format contract stays independent of the embedded-cover-art surface.
    """

    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"


class NetworkLagEffect(enum.StrEnum):
    """Watcher-visible filesystem lag artifact requested by a lag window."""

    DELAYED_VISIBILITY = "delayed_visibility"
    DELAYED_RENAME = "delayed_rename"
    HELD_HANDLE = "held_handle"


class ReadonlyState(enum.StrEnum):
    """Read/write state requested by ``toggle_readonly``."""

    READONLY = "readonly"
    READWRITE = "readwrite"


class LockType(enum.StrEnum):
    """Advisory lock kind requested by ``acquire_lock``."""

    SHARED = "shared"
    EXCLUSIVE = "exclusive"


class PacketStreamKind(enum.StrEnum):
    """Stream kinds selectable by packet-range corruption."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


# ---- Library ----------------------------------------------------------------


# Every model in the Scenario subtree below is frozen with tuple
# collection fields. ``RunInput.scenario`` caches one parsed Scenario
# across the validation pipeline, plan, replay, and materialize; any
# mutation between validation and the engine would desync generated
# artifacts from the bytes the replay bundle records. Pydantic still
# accepts list input and coerces to tuple at validation time, so the
# wire format is unchanged.


class LibraryRoot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    path: str


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    roots: tuple[LibraryRoot, ...]
    archive_root: str | None = None


# ---- Tracks -----------------------------------------------------------------


class VideoTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: VideoSource
    codec: str
    resolution: str
    vfr_cadence: VideoVfrCadence | None = None
    field_order: VideoFieldOrder | None = None
    color_space: VideoColorSpace | None = None
    color_range: VideoColorRange | None = None
    hdr_mode: VideoHdrMode | None = None
    resolution_sequence: VideoResolutionSequence | None = None

    @field_validator("vfr_cadence", mode="before")
    @classmethod
    def _coerce_yaml_numeric_vfr_cadence(cls, value: object) -> object:
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value == _YAML_NUMERIC_VFR_24_30_60
        ):
            return VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY.value
        return value


class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: AudioSource = AudioSource.SINE
    codec: str
    channels: AudioChannelLayout
    language: str
    role: AudioTrackRole = AudioTrackRole.MAIN
    noise_color: AudioNoiseColor | None = None
    sample_rate: Literal[8000, 22050, 44100, 48000, 88200, 96000] = 48000
    sample_format: AudioSampleFormat | None = None

    @model_validator(mode="after")
    def _validate_noise_color(self) -> AudioTrack:
        if self.source is AudioSource.NOISE and self.noise_color is None:
            raise ValueError("audio noise source requires noise_color")
        if self.source is not AudioSource.NOISE and self.noise_color is not None:
            raise ValueError("noise_color is only valid with source='noise'")
        return self


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: SubtitleSource = SubtitleSource.GENERATED_SRT
    codec: SubtitleCodec
    language: str
    mode: SubtitleMode
    encoding: SubtitleEncoding = SubtitleEncoding.UTF8
    timing_profile: SubtitleTimingProfile = SubtitleTimingProfile.NORMAL


class EmbeddedChapters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=1, le=20)
    title_prefix: str = Field(default="Chapter", min_length=1, max_length=64)


class EmbeddedCoverArt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: CoverArtSource = CoverArtSource.SOLID_COLOR
    image_format: CoverArtImageFormat = CoverArtImageFormat.PNG
    resolution: CoverArtResolution = CoverArtResolution.SQUARE_320


# ---- Asset / Bundle / Variant / Domain hierarchy ----------------------------


class SymlinkTarget(BaseModel):
    """Declares the target of an asset materialized as an ``os.symlink``.

    Exactly one of the two forms is set: ``to_asset`` references another
    earlier-declared asset whose in-library file the link points at (an
    in-root link), and ``to_run_dir_path`` is a relative path resolving inside
    the run dir but outside ``library/`` (a library-escaping link). The two
    forms validate differently — ``to_asset`` is an asset-id reference
    (``rule_content_reference`` → ``E_TARGET_UNKNOWN``), ``to_run_dir_path`` is
    a sandboxed path (``rule_symlink_target_escape`` → ``E_SYMLINK_TARGET_ESCAPE``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    to_asset: str | None = None
    to_run_dir_path: str | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> SymlinkTarget:
        if (self.to_asset is None) == (self.to_run_dir_path is None):
            raise ValueError("symlink requires exactly one of to_asset / to_run_dir_path")
        return self


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    role: str
    container: str
    duration_seconds: float
    mp4_moov_placement: Mp4MoovPlacement | None = None
    matroska_muxing_profile: MatroskaMuxingProfile | None = None
    embedded_chapters: EmbeddedChapters | None = None
    embedded_cover_art: EmbeddedCoverArt | None = None
    video: VideoTrack | None = None
    audio: tuple[AudioTrack, ...] = Field(default_factory=tuple)
    subtitles: tuple[SubtitleTrack, ...] = Field(default_factory=tuple)
    # Content-dedup / shared-inode authoring knobs. ``same_content_as`` (v25)
    # copies another asset's materialized bytes verbatim (same full content_hash,
    # independent files); ``hash_collision_with`` + ``collision_prefix_len`` (v25)
    # make this asset's *recorded* hash share a truncated hex prefix with another
    # asset's while the on-disk bytes differ (oracle-recorded collision);
    # ``hardlinked_to`` (v26) makes this asset's path a *hardlink* to another
    # asset's already-written file via ``os.link`` (one shared inode, link count
    # >= 2), distinct from ``same_content_as``'s byte copy. ``symlink`` (v27)
    # makes this asset's path an ``os.symlink`` to either an in-root asset's file
    # (``to_asset``) or a library-escaping run-dir path (``to_run_dir_path``). The
    # four link fields are mutually exclusive; cross-asset reference resolution
    # and escaping-target sandboxing are semantic rules.
    same_content_as: str | None = None
    hash_collision_with: str | None = None
    collision_prefix_len: int | None = Field(default=None, ge=1, le=63)
    hardlinked_to: str | None = None
    symlink: SymlinkTarget | None = None

    @model_validator(mode="after")
    def _check_content_dedup_fields(self) -> Asset:
        if self.same_content_as is not None and self.hash_collision_with is not None:
            raise ValueError("same_content_as and hash_collision_with are mutually exclusive")
        if self.hardlinked_to is not None and self.same_content_as is not None:
            raise ValueError("hardlinked_to and same_content_as are mutually exclusive")
        if self.hardlinked_to is not None and self.hash_collision_with is not None:
            raise ValueError("hardlinked_to and hash_collision_with are mutually exclusive")
        if self.symlink is not None and self.same_content_as is not None:
            raise ValueError("symlink and same_content_as are mutually exclusive")
        if self.symlink is not None and self.hash_collision_with is not None:
            raise ValueError("symlink and hash_collision_with are mutually exclusive")
        if self.symlink is not None and self.hardlinked_to is not None:
            raise ValueError("symlink and hardlinked_to are mutually exclusive")
        if (self.hash_collision_with is None) != (self.collision_prefix_len is None):
            raise ValueError(
                "collision_prefix_len must be set if and only if hash_collision_with is set"
            )
        if self.same_content_as is not None and self.subtitles:
            raise ValueError("same_content_as forbids declaring the asset's own subtitles")
        if self.hardlinked_to is not None and self.subtitles:
            raise ValueError("hardlinked_to forbids declaring the asset's own subtitles")
        if self.symlink is not None and self.subtitles:
            raise ValueError("symlink forbids declaring the asset's own subtitles")
        return self


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    assets: tuple[Asset, ...]


class EditionKind(enum.StrEnum):
    """Movie release/edition cut, rendered as a Plex/Jellyfin {edition-...} token."""

    THEATRICAL = "theatrical"
    DIRECTORS_CUT = "directors_cut"
    EXTENDED = "extended"
    UNRATED = "unrated"


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    label: str
    # Optional movie edition (theatrical/director's cut/...). None for the common
    # single-edition case and for non-movie variants; only the movie render branch
    # emits the {edition-...} token. See ADR 0010.
    edition: EditionKind | None = None
    bundle: Bundle


class MovieLayout(enum.StrEnum):
    MOVIE_FLAT = "movie_flat"
    MOVIE_FOLDER = "movie_folder"


class SeriesLayout(enum.StrEnum):
    SEASON_FOLDERS = "season_folders"
    SERIES_FLAT = "series_flat"


class EpisodeNaming(enum.StrEnum):
    SXXEXX_TITLE = "sxxexx_title"
    ONE_XX_TITLE = "one_xx_title"
    ABSOLUTE_3_DIGIT_TITLE = "absolute_3_digit_title"
    DATE_TITLE = "date_title"


class ArtistLayout(enum.StrEnum):
    ARTIST_ALBUM_DISC = "artist_album_disc"
    ARTIST_ALBUM_FLAT = "artist_album_flat"


class TrackNaming(enum.StrEnum):
    TRACK_NUMBER_TITLE = "track_number_title"
    DISC_TRACK_NUMBER_TITLE = "disc_track_number_title"


class Movie(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: MovieLayout
    variants: tuple[Variant, ...]


class Episode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    episode_number: int = Field(ge=1)
    title: str
    aired_on: date | None = None
    absolute_number: int | None = Field(default=None, ge=1)
    variants: tuple[Variant, ...]


class Season(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    season_number: int = Field(ge=0)
    title: str
    episodes: tuple[Episode, ...]


class Series(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: SeriesLayout
    episode_naming: EpisodeNaming
    seasons: tuple[Season, ...]


class Track(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    track_number: int = Field(ge=1)
    title: str
    performers: tuple[str, ...] = Field(default_factory=tuple)
    variants: tuple[Variant, ...]


class Disc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    disc_number: int = Field(ge=1)
    tracks: tuple[Track, ...]


class Album(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    release_year: int | None = None
    discs: tuple[Disc, ...]


class Artist(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    layout: ArtistLayout
    track_naming: TrackNaming
    albums: tuple[Album, ...]


class PodcastLayout(enum.StrEnum):
    PODCAST_FOLDER = "podcast_folder"


class PodcastEpisodeNaming(enum.StrEnum):
    DATE_SLUG_TITLE = "date_slug_title"


class PodcastEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    # Aware RFC3339 datetime, required UTC (see _require_utc). The full instant
    # drives deterministic ordering; only the UTC date renders into the path.
    published_at: datetime
    # Required uniqueness tiebreaker so two same-published_at episodes still
    # render distinct paths (scenario v30).
    slug: str = Field(min_length=1)
    # Recorded state: episode absent from the source feed but file lingering.
    # mark_episode_stale is the primary transition; this is the initial value.
    stale: bool = False
    variants: tuple[Variant, ...]

    @model_validator(mode="after")
    def _require_utc(self) -> PodcastEpisode:
        offset = self.published_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("published_at must be a UTC datetime (Z / +00:00)")
        return self


class Podcast(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: PodcastLayout
    episode_naming: PodcastEpisodeNaming
    episodes: tuple[PodcastEpisode, ...]


# ---- Timeline events --------------------------------------------------------


class _TimelineEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)
    id: str
    at: str


class MoveAssetEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_ASSET] = TimelineActionName.MOVE_ASSET
    target: str
    to: str


class RenameFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENAME_FILE] = TimelineActionName.RENAME_FILE
    target: str
    to: str


class DeleteFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.DELETE_FILE] = TimelineActionName.DELETE_FILE
    target: str


class AddFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.ADD_FILE] = TimelineActionName.ADD_FILE
    target: str
    to: str


class ReencodeVideoEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REENCODE_VIDEO] = TimelineActionName.REENCODE_VIDEO
    target: str
    resolution: str
    codec: str


class ReencodeAudioEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REENCODE_AUDIO] = TimelineActionName.REENCODE_AUDIO
    target: str
    from_channels: AudioChannelLayout
    to_channels: AudioChannelLayout


class CreateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CREATE_SIDECAR] = TimelineActionName.CREATE_SIDECAR
    target: str
    to: str
    # Widened in scenario v5: poster/NFO sidecars have no language. The
    # model_validator below enforces (kind=subtitle, language=...) /
    # (kind in {poster, nfo}, language=None).
    language: str | None = None
    kind: SidecarKind = SidecarKind.SUBTITLE
    # Authoring knobs (scenario v24+). Each is scoped to one kind; the
    # model_validator forbids cross-kind misuse. None selects the kind's
    # current default (srt/generated_srt/utf8 subtitle, template NFO, image poster,
    # default CUE). ``image_format`` (v32, #118) is poster-only and selects the
    # synthesized poster image format (png/jpeg/webp); ``body`` also serves cue.
    codec: SubtitleCodec | None = None
    source: SubtitleSource | None = None
    encoding: SubtitleEncoding | None = None
    body: str | None = Field(default=None, min_length=1)
    media_type: SidecarMediaType | None = None
    image_format: PosterImageFormat | None = None

    @model_validator(mode="after")
    def _check_fields_match_kind(self) -> CreateSidecarEvent:
        if self.kind == SidecarKind.SUBTITLE and self.language is None:
            raise ValueError("subtitle sidecar requires language")
        if self.kind != SidecarKind.SUBTITLE and self.language is not None:
            raise ValueError(f"{self.kind.value} sidecar forbids language")
        if self.kind != SidecarKind.SUBTITLE:
            for name, value in (
                ("codec", self.codec),
                ("source", self.source),
                ("encoding", self.encoding),
            ):
                if value is not None:
                    raise ValueError(f"{name} is only valid for subtitle sidecars")
        if self.kind not in {SidecarKind.NFO, SidecarKind.CUE} and self.body is not None:
            raise ValueError("body is only valid for nfo and cue sidecars")
        if self.kind != SidecarKind.POSTER and self.media_type is not None:
            raise ValueError("media_type is only valid for poster sidecars")
        if self.kind != SidecarKind.POSTER and self.image_format is not None:
            raise ValueError("image_format is only valid for poster sidecars")
        if self.image_format is not None and self.media_type is SidecarMediaType.VIDEO:
            raise ValueError("image_format cannot be combined with media_type=video")
        return self


class SlowCopyStartEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SLOW_COPY_START] = TimelineActionName.SLOW_COPY_START
    target: str
    to: str
    temp_path: str
    duration: str


class SlowCopyCommitEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SLOW_COPY_COMMIT] = TimelineActionName.SLOW_COPY_COMMIT
    # `for` is a Python keyword; map to `for_` in Python. Use split aliases
    # (validation + serialization) instead of a single ``alias=`` so the Python
    # field name remains the ``__init__`` parameter that ty sees.
    for_: str = Field(
        validation_alias=AliasChoices("for_", "for"),
        serialization_alias="for",
    )


class ArchiveFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.ARCHIVE_FILE] = TimelineActionName.ARCHIVE_FILE
    target: str


class MoveBetweenRootsEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_BETWEEN_ROOTS] = TimelineActionName.MOVE_BETWEEN_ROOTS
    target: str
    from_root_id: str
    to_root_id: str


class RemuxContainerEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMUX_CONTAINER] = TimelineActionName.REMUX_CONTAINER
    target: str
    # "mp4" / "mkv" / "webm" — engine rewrites the path extension;
    # materializer runs ffmpeg -c copy.
    to_container: str


class EditMetadataEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EDIT_METADATA] = TimelineActionName.EDIT_METADATA
    target: str
    # Opaque key=value pairs; materializer maps each to ffmpeg -metadata.
    # Empty dict rejected here.
    fields: dict[str, str]

    @model_validator(mode="after")
    def _check_fields_non_empty(self) -> EditMetadataEvent:
        if not self.fields:
            raise ValueError("edit_metadata.fields must be a non-empty mapping")
        return self


class EmbedSubtitleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EMBED_SUBTITLE] = TimelineActionName.EMBED_SUBTITLE
    target: str
    # For a DECLARED subtitle, use ``"<asset_id>.<language>.srt"`` (see
    # Sprint 7 spec §"Declared-sidecar path convention"). For a sidecar
    # created by ``create_sidecar``, use that event's ``to:`` path.
    sidecar_path: str


class ExtractSubtitleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EXTRACT_SUBTITLE] = TimelineActionName.EXTRACT_SUBTITLE
    target: str
    to: str
    language: str
    # Embedded-track selection: extract the first subtitle track of the
    # asset whose language matches. If no language match, falls back to
    # the first subtitle track. Validator rejects if asset has no
    # subtitle track via E_EXTRACT_TRACK_UNKNOWN.


class RemoveSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMOVE_SIDECAR] = TimelineActionName.REMOVE_SIDECAR
    target: str
    sidecar_path: str


class UpdateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.UPDATE_SIDECAR] = TimelineActionName.UPDATE_SIDECAR
    target: str
    sidecar_path: str


class CorruptContainerHeaderEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CORRUPT_CONTAINER_HEADER] = (
        TimelineActionName.CORRUPT_CONTAINER_HEADER
    )
    target: str
    # Number of leading header bytes to overwrite; default clobbers the first
    # 64 bytes, upper bound caps how much of the header region is affected.
    bytes: int = Field(default=64, ge=1, le=4096)


class TruncateFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.TRUNCATE_FILE] = TimelineActionName.TRUNCATE_FILE
    target: str
    keep_bytes: int = Field(ge=1)


class CorruptPacketRangeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CORRUPT_PACKET_RANGE] = (
        TimelineActionName.CORRUPT_PACKET_RANGE
    )
    target: str
    stream: PacketStreamKind = PacketStreamKind.VIDEO
    packet_start: int = Field(ge=0)
    # Number of consecutive packets to corrupt; default corrupts a single
    # packet, upper bound caps the corruption span.
    packet_count: int = Field(default=1, ge=1, le=128)


class WriteInvalidDurationMetadataEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.WRITE_INVALID_DURATION_METADATA] = (
        TimelineActionName.WRITE_INVALID_DURATION_METADATA
    )
    target: str
    value: str = Field(default="not-a-duration", min_length=1, max_length=128)


class TouchMtimeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.TOUCH_MTIME] = TimelineActionName.TOUCH_MTIME
    target: str
    offset: str = Field(min_length=1)


class WrongOracleHashEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.WRONG_ORACLE_HASH] = TimelineActionName.WRONG_ORACLE_HASH
    target: str


class NetworkLagStartEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.NETWORK_LAG_START] = TimelineActionName.NETWORK_LAG_START
    effect: NetworkLagEffect
    target: str
    after: str
    duration: str


class NetworkLagCommitEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.NETWORK_LAG_COMMIT] = TimelineActionName.NETWORK_LAG_COMMIT
    # `for` is a Python keyword; keep the same Python/YAML split as slow copy.
    for_: str = Field(
        validation_alias=AliasChoices("for_", "for"),
        serialization_alias="for",
    )


# Octal permission string for change_permissions: 3 or 4 octal digits.
_PERMISSION_MODE_PATTERN: Final = r"^[0-7]{3,4}$"


class ChangePermissionsEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CHANGE_PERMISSIONS] = TimelineActionName.CHANGE_PERMISSIONS
    # target is a declared asset id or a library-relative subtree path.
    target: str
    mode: str = Field(pattern=_PERMISSION_MODE_PATTERN)


class SimulateQuotaExceededEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SIMULATE_QUOTA_EXCEEDED] = (
        TimelineActionName.SIMULATE_QUOTA_EXCEEDED
    )
    target: str


class ToggleReadonlyEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.TOGGLE_READONLY] = TimelineActionName.TOGGLE_READONLY
    # target is a declared asset id or a library-relative subtree path.
    target: str
    mode: ReadonlyState


class SimulateStaleHandleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SIMULATE_STALE_HANDLE] = (
        TimelineActionName.SIMULATE_STALE_HANDLE
    )
    target: str


class UnmountPathEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.UNMOUNT_PATH] = TimelineActionName.UNMOUNT_PATH
    # target is a declared asset id or a library-relative subtree path.
    target: str


class RemountPathEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMOUNT_PATH] = TimelineActionName.REMOUNT_PATH
    # `for` is a Python keyword; keep the same Python/YAML split as slow copy.
    # References the unmount_path event id this remount closes.
    for_: str = Field(
        validation_alias=AliasChoices("for_", "for"),
        serialization_alias="for",
    )


class AcquireLockEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.ACQUIRE_LOCK] = TimelineActionName.ACQUIRE_LOCK
    target: str
    lock_type: LockType


class ReleaseLockEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RELEASE_LOCK] = TimelineActionName.RELEASE_LOCK
    # References the acquire_lock event id this release closes.
    for_: str = Field(
        validation_alias=AliasChoices("for_", "for"),
        serialization_alias="for",
    )


class RenumberEpisodeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENUMBER_EPISODE] = TimelineActionName.RENUMBER_EPISODE
    target: str
    episode_number: int = Field(ge=1)
    absolute_number: int | None = Field(default=None, ge=1)


class MoveEpisodeToSeasonEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_EPISODE_TO_SEASON] = (
        TimelineActionName.MOVE_EPISODE_TO_SEASON
    )
    target: str
    to_season: str
    episode_number: int = Field(ge=1)
    absolute_number: int | None = Field(default=None, ge=1)


class RenameSeasonEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENAME_SEASON] = TimelineActionName.RENAME_SEASON
    target: str
    title: str


class RenumberDiscEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENUMBER_DISC] = TimelineActionName.RENUMBER_DISC
    target: str
    disc_number: int = Field(ge=1)


class MoveTrackToDiscEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_TRACK_TO_DISC] = TimelineActionName.MOVE_TRACK_TO_DISC
    target: str
    to_disc: str
    track_number: int = Field(ge=1)


class SwapEpisodeNumbersEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SWAP_EPISODE_NUMBERS] = (
        TimelineActionName.SWAP_EPISODE_NUMBERS
    )
    target: str
    with_episode: str


class SwapDiscNumbersEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SWAP_DISC_NUMBERS] = TimelineActionName.SWAP_DISC_NUMBERS
    target: str
    with_disc: str


class SwapTrackNumbersEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.SWAP_TRACK_NUMBERS] = TimelineActionName.SWAP_TRACK_NUMBERS
    target: str
    with_track: str


class RepublishEpisodeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REPUBLISH_EPISODE] = TimelineActionName.REPUBLISH_EPISODE
    target: str
    # New UTC publish instant; re-renders the episode's path. An optional slug
    # lets the author also change the path tiebreaker in the same transition.
    published_at: datetime
    slug: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _require_utc(self) -> RepublishEpisodeEvent:
        offset = self.published_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("published_at must be a UTC datetime (Z / +00:00)")
        return self


class MarkEpisodeStaleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MARK_EPISODE_STALE] = TimelineActionName.MARK_EPISODE_STALE
    target: str


class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    movies: int = Field(ge=0)
    series: int = Field(ge=0)
    seasons: int = Field(ge=0)
    episodes: int = Field(ge=0)
    artists: int = Field(ge=0)
    albums: int = Field(ge=0)
    discs: int = Field(ge=0)
    tracks: int = Field(ge=0)
    variants: int = Field(ge=0)
    bundles: int = Field(ge=0)
    assets: int = Field(ge=0)
    sidecars: int = Field(ge=0)
    timeline_events: int = Field(ge=0)


class ScenarioGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: Literal["chaos-librarian"] = "chaos-librarian"
    profile: FuzzProfileName
    lane: FuzzLaneName
    profile_version: Literal[3]
    seed: int = Field(ge=0)
    budgets: GenerationBudget


FUZZ_GENERATION_PROFILE_VERSION: Final = 3

FUZZ_GENERATION_BUDGETS: Final[dict[FuzzProfileName, GenerationBudget]] = {
    FuzzProfileName.FUZZ_SMOKE: GenerationBudget(
        movies=3,
        series=0,
        seasons=0,
        episodes=0,
        artists=0,
        albums=0,
        discs=0,
        tracks=0,
        variants=4,
        bundles=4,
        assets=4,
        sidecars=8,
        timeline_events=12,
    ),
    FuzzProfileName.FUZZ_REGRESSION: GenerationBudget(
        movies=12,
        series=1,
        seasons=2,
        episodes=2,
        artists=1,
        albums=1,
        discs=2,
        tracks=2,
        variants=22,
        bundles=22,
        assets=22,
        sidecars=54,
        timeline_events=80,
    ),
}


def generation_budget_for(profile: FuzzProfileName) -> GenerationBudget:
    """Return the canonical generation budget for a fuzz profile."""
    return FUZZ_GENERATION_BUDGETS[profile]


TimelineEvent = Annotated[
    MoveAssetEvent
    | RenameFileEvent
    | DeleteFileEvent
    | AddFileEvent
    | ReencodeVideoEvent
    | ReencodeAudioEvent
    | CreateSidecarEvent
    | SlowCopyStartEvent
    | SlowCopyCommitEvent
    | ArchiveFileEvent
    | MoveBetweenRootsEvent
    | RemuxContainerEvent
    | EditMetadataEvent
    | EmbedSubtitleEvent
    | ExtractSubtitleEvent
    | RemoveSidecarEvent
    | UpdateSidecarEvent
    | CorruptContainerHeaderEvent
    | TruncateFileEvent
    | CorruptPacketRangeEvent
    | WriteInvalidDurationMetadataEvent
    | TouchMtimeEvent
    | WrongOracleHashEvent
    | NetworkLagStartEvent
    | NetworkLagCommitEvent
    | ChangePermissionsEvent
    | SimulateQuotaExceededEvent
    | ToggleReadonlyEvent
    | SimulateStaleHandleEvent
    | UnmountPathEvent
    | RemountPathEvent
    | AcquireLockEvent
    | ReleaseLockEvent
    | RenumberEpisodeEvent
    | MoveEpisodeToSeasonEvent
    | RenameSeasonEvent
    | RenumberDiscEvent
    | MoveTrackToDiscEvent
    | SwapEpisodeNumbersEvent
    | SwapDiscNumbersEvent
    | SwapTrackNumbersEvent
    | RepublishEpisodeEvent
    | MarkEpisodeStaleEvent,
    Field(discriminator="action"),
]


# ---- Scenario ---------------------------------------------------------------


class Scenario(BaseModel):
    # See subtree-immutability note above the ``LibraryRoot`` declaration.
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    schema_version: Literal[32]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: DurationScale
    profiles: tuple[ProfileName, ...] = Field(default_factory=tuple)
    generation: ScenarioGeneration | None = None
    library: Library
    movies: tuple[Movie, ...]
    series: tuple[Series, ...]
    artists: tuple[Artist, ...]
    podcasts: tuple[Podcast, ...] = Field(default_factory=tuple)
    timeline: tuple[TimelineEvent, ...]

    @model_validator(mode="after")
    def _check_generation_metadata(self) -> Scenario:
        if self.generation is None:
            return self

        profile = ProfileName(self.generation.profile.value)
        if profile not in self.profiles:
            raise ValueError("generation.profile must be listed in profiles")
        if self.seed == "random":
            raise ValueError("generation.seed requires concrete scenario seed")
        if self.seed != self.generation.seed:
            raise ValueError("generation.seed must match scenario seed")
        allowed_lanes = FUZZ_LANES_BY_PROFILE[self.generation.profile]
        if self.generation.lane not in allowed_lanes:
            raise ValueError("generation.lane must match generation.profile")
        expected = generation_budget_for(self.generation.profile)
        if self.generation.budgets != expected:
            raise ValueError("generation.budgets must match the selected profile")
        return self
