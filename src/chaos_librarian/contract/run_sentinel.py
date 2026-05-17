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


class RunSentinel(BaseModel):
    """Top-level ``.chaos-librarian-run`` sentinel file."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    # ty rejects ``Literal[CONSTANT]`` (PEP 586 indirect form); hardcode the
    # value here. test_rejects_unknown_schema_version locks the linkage to
    # RUN_SENTINEL_SCHEMA_VERSION via the constant value.
    schema_version: Literal[1]
    created_by: str
    created_at: datetime | None = None
