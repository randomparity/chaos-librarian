"""Scenario schema: input YAML format for chaos-librarian.

Mirrors the example in docs/specs/chaos-librarian-design.md "Scenario Format".
Timeline events are a discriminated union on ``action``.
"""

from __future__ import annotations

import enum
from typing import Annotated, Final, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


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


ALL_TIMELINE_ACTIONS: Final[frozenset[str]] = frozenset(TimelineActionName)


class VideoSource(enum.StrEnum):
    """Synthesis recipe for the video stream of an asset."""

    MANDELBROT = "mandelbrot"
    COLOR_BARS = "color_bars"
    SOLID_COLOR = "solid_color"
    NOISE = "noise"  # passes validate; not yet supported by materialize


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


class SubtitleSource(enum.StrEnum):
    """Synthesis recipe for a subtitle track."""

    GENERATED_SRT = "generated_srt"


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
    channels: str
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
    from_channels: str
    to_channels: str


class CreateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CREATE_SIDECAR] = TimelineActionName.CREATE_SIDECAR
    target: str
    to: str
    # Required from scenario v3 (manifest v3 keys ManifestSidecar lookups on
    # ``(asset_id, language)``). Engine writes this onto the
    # ``ManifestSidecar`` row so plan-only consumers can resolve the row by
    # the same key materialized rows use.
    language: str


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


TimelineEvent = Annotated[
    MoveAssetEvent
    | RenameFileEvent
    | DeleteFileEvent
    | AddFileEvent
    | ReencodeVideoEvent
    | ReencodeAudioEvent
    | CreateSidecarEvent
    | SlowCopyStartEvent
    | SlowCopyCommitEvent,
    Field(discriminator="action"),
]


# ---- Scenario ---------------------------------------------------------------


class Scenario(BaseModel):
    # See subtree-immutability note above the ``LibraryRoot`` declaration.
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    schema_version: Literal[3]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: DurationScale
    library: Library
    works: tuple[Work, ...]
    timeline: tuple[TimelineEvent, ...]
