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
    NOISE = "noise"  # Sprint 6+ in materialize; passes validate today.


class AudioSource(enum.StrEnum):
    """Synthesis recipe for an audio stream."""

    SINE = "sine"
    SILENCE = "silence"
    CHANNEL_TONES = "channel_tones"


class SubtitleSource(enum.StrEnum):
    """Synthesis recipe for a subtitle track."""

    GENERATED_SRT = "generated_srt"


# ---- Library ----------------------------------------------------------------


class LibraryRoot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roots: list[LibraryRoot]


# ---- Tracks -----------------------------------------------------------------


class VideoTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: VideoSource
    codec: str
    resolution: str


class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: AudioSource = AudioSource.SINE
    codec: str
    channels: str
    language: str


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: SubtitleSource = SubtitleSource.GENERATED_SRT
    codec: str
    language: str
    mode: Literal["embedded", "sidecar"]


# ---- Asset / Bundle / Variant / Work ----------------------------------------


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    role: str
    container: str
    duration_seconds: float
    video: VideoTrack | None = None
    audio: list[AudioTrack] = Field(default_factory=list)
    subtitles: list[SubtitleTrack] = Field(default_factory=list)


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    assets: list[Asset]


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    bundle: Bundle


class Work(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    variants: list[Variant]


# ---- Timeline events --------------------------------------------------------


class _TimelineEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
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
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[2]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: Literal["short", "normal", "long"]
    library: Library
    works: list[Work]
    timeline: list[TimelineEvent]
