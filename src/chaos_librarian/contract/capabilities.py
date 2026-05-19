"""Capability-detection report schema.

Output of ``chaos-librarian capabilities --json``. Materialize re-runs
the same detection at startup and refuses (exit 4) if the gate regresses.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ToolStatus(BaseModel):
    """Detection outcome for one external tool."""

    model_config = ConfigDict(extra="forbid")

    found: bool
    version: str | None = None
    path: str | None = None
    meets_minimum: bool


class ReadyFor(BaseModel):
    """Forward-looking signals — which materialize modes the toolchain supports.

    The current CLI only consults ``materialize_static``. The other two
    flags are populated so adapter authors can skip the corresponding
    mutation-mode tests cleanly.
    """

    model_config = ConfigDict(extra="forbid")

    materialize_static: bool
    materialize_filesystem_mutations: bool
    materialize_media_mutations: bool


class Capabilities(BaseModel):
    """Full ``capabilities --json`` payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    mkvtoolnix: ToolStatus
    platform: str
    ready_for: ReadyFor
