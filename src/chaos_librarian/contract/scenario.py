"""Scenario schema: input YAML format for chaos-librarian.

Mirrors the example in docs/specs/chaos-librarian-design.md "Scenario Format".
Timeline events are a discriminated union on ``action``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

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
    source: str
    codec: str
    resolution: str


class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codec: str
    channels: str
    language: str


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
    action: Literal["move_asset"] = "move_asset"
    target: str
    to: str


class RenameFileEvent(_TimelineEventBase):
    action: Literal["rename_file"] = "rename_file"
    target: str
    to: str


class DeleteFileEvent(_TimelineEventBase):
    action: Literal["delete_file"] = "delete_file"
    target: str


class AddFileEvent(_TimelineEventBase):
    action: Literal["add_file"] = "add_file"
    target: str
    to: str


class ReencodeVideoEvent(_TimelineEventBase):
    action: Literal["reencode_video"] = "reencode_video"
    target: str
    resolution: str
    codec: str


class ReencodeAudioEvent(_TimelineEventBase):
    action: Literal["reencode_audio"] = "reencode_audio"
    target: str
    from_channels: str
    to_channels: str


class CreateSidecarEvent(_TimelineEventBase):
    action: Literal["create_sidecar"] = "create_sidecar"
    target: str
    to: str


class SlowCopyStartEvent(_TimelineEventBase):
    action: Literal["slow_copy_start"] = "slow_copy_start"
    target: str
    to: str
    temp_path: str
    duration: str


class SlowCopyCommitEvent(_TimelineEventBase):
    action: Literal["slow_copy_commit"] = "slow_copy_commit"
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

    schema_version: Literal[1]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: Literal["short", "normal", "long"]
    library: Library
    works: list[Work]
    timeline: list[TimelineEvent]
