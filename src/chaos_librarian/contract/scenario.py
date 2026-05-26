"""Scenario schema: input YAML format for chaos-librarian.

Mirrors the example in docs/specs/chaos-librarian-design.md "Scenario Format".
Timeline events are a discriminated union on ``action``.
"""

from __future__ import annotations

import enum
from typing import Annotated, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName


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


ALL_TIMELINE_ACTIONS: Final[frozenset[str]] = frozenset(TimelineActionName)


class VideoSource(enum.StrEnum):
    """Synthesis recipe for the video stream of an asset."""

    MANDELBROT = "mandelbrot"
    COLOR_BARS = "color_bars"
    SOLID_COLOR = "solid_color"
    NOISE = "noise"  # reserved; validate rejects it until materialize supports it


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


class AudioChannelLayout(enum.StrEnum):
    """Supported author-facing audio channel layouts."""

    MONO = "mono"
    STEREO = "stereo"
    TWO_ONE = "2.1"
    FIVE_ONE = "5.1"
    SEVEN_ONE = "7.1"


AUDIO_CHANNEL_COUNTS_BY_NAME: Final[dict[str, int]] = {
    AudioChannelLayout.MONO.value: 1,
    AudioChannelLayout.STEREO.value: 2,
    AudioChannelLayout.TWO_ONE.value: 3,
    AudioChannelLayout.FIVE_ONE.value: 6,
    AudioChannelLayout.SEVEN_ONE.value: 8,
}


class SubtitleSource(enum.StrEnum):
    """Synthesis recipe for a subtitle track."""

    GENERATED_SRT = "generated_srt"


class SidecarKind(enum.StrEnum):
    """Kind of a sidecar — extends Sprint 6's subtitle-only assumption.

    Subtitle requires ``language``; poster and NFO forbid it.
    """

    SUBTITLE = "subtitle"
    POSTER = "poster"
    NFO = "nfo"


class NetworkLagEffect(enum.StrEnum):
    """Watcher-visible filesystem lag artifact requested by a lag window."""

    DELAYED_VISIBILITY = "delayed_visibility"
    DELAYED_RENAME = "delayed_rename"
    HELD_HANDLE = "held_handle"


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


class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: AudioSource = AudioSource.SINE
    codec: str
    channels: AudioChannelLayout
    language: str


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: SubtitleSource = SubtitleSource.GENERATED_SRT
    codec: str
    language: str
    mode: SubtitleMode


# ---- Asset / Bundle / Variant / Work ----------------------------------------


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    role: str
    container: str
    duration_seconds: float
    video: VideoTrack | None = None
    audio: tuple[AudioTrack, ...] = Field(default_factory=tuple)
    subtitles: tuple[SubtitleTrack, ...] = Field(default_factory=tuple)


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    assets: tuple[Asset, ...]


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    label: str
    bundle: Bundle


class Work(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    variants: tuple[Variant, ...]


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

    @model_validator(mode="after")
    def _check_language_matches_kind(self) -> CreateSidecarEvent:
        if self.kind == SidecarKind.SUBTITLE and self.language is None:
            raise ValueError("subtitle sidecar requires language")
        if self.kind != SidecarKind.SUBTITLE and self.language is not None:
            raise ValueError(f"{self.kind.value} sidecar forbids language")
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


class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    works: int = Field(ge=0)
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
    profile_version: Literal[2]
    seed: int = Field(ge=0)
    budgets: GenerationBudget


FUZZ_GENERATION_PROFILE_VERSION: Final = 2

FUZZ_GENERATION_BUDGETS: Final[dict[FuzzProfileName, GenerationBudget]] = {
    FuzzProfileName.FUZZ_SMOKE: GenerationBudget(
        works=3,
        variants=4,
        bundles=4,
        assets=4,
        sidecars=8,
        timeline_events=12,
    ),
    FuzzProfileName.FUZZ_REGRESSION: GenerationBudget(
        works=12,
        variants=18,
        bundles=18,
        assets=18,
        sidecars=54,
        timeline_events=80,
    ),
}


FUZZ_LANES_BY_PROFILE: Final[dict[FuzzProfileName, frozenset[FuzzLaneName]]] = {
    FuzzProfileName.FUZZ_SMOKE: frozenset({FuzzLaneName.SMOKE}),
    FuzzProfileName.FUZZ_REGRESSION: frozenset(
        {
            FuzzLaneName.CORE_FS,
            FuzzLaneName.MEDIA_REWRITE,
            FuzzLaneName.SIDECAR_SUBTITLE,
            FuzzLaneName.MALFORMED,
            FuzzLaneName.NEGATIVE_ORACLE,
            FuzzLaneName.FILESYSTEM_ARTIFACT,
            FuzzLaneName.NETWORK_LAG,
        }
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
    | NetworkLagCommitEvent,
    Field(discriminator="action"),
]


# ---- Scenario ---------------------------------------------------------------


class Scenario(BaseModel):
    # See subtree-immutability note above the ``LibraryRoot`` declaration.
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    schema_version: Literal[11]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: DurationScale
    profiles: tuple[ProfileName, ...] = Field(default_factory=tuple)
    generation: ScenarioGeneration | None = None
    library: Library
    works: tuple[Work, ...]
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
