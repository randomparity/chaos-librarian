"""Run-directory sentinel.

Every run directory created by chaos-librarian contains a top-level
``.chaos-librarian-run`` JSON file that proves the directory was created by
this tool. See docs/specs/chaos-librarian-design.md "Run-Directory Sentinel".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION


class RunSentinel(BaseModel):
    """Top-level ``.chaos-librarian-run`` sentinel file."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    schema_version: Literal[RUN_SENTINEL_SCHEMA_VERSION]  # ty:ignore[invalid-type-form]
    created_by: str
    created_at: datetime | None = None
