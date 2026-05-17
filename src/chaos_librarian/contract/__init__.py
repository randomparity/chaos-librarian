"""Schema source-of-truth: Pydantic v2 models exported as JSON Schema."""

from __future__ import annotations

import uuid
from typing import Final

# Schema versions. Bumps are always breaking (no minor versions).
# See docs/specs/chaos-librarian-design.md "Versioning".
SCENARIO_SCHEMA_VERSION: Final[int] = 1
MANIFEST_SCHEMA_VERSION: Final[int] = 1
JOURNAL_SCHEMA_VERSION: Final[int] = 1
REPLAY_BUNDLE_SCHEMA_VERSION: Final[int] = 1
VALIDATION_SCHEMA_VERSION: Final[int] = 1
MATERIALIZATION_SCHEMA_VERSION: Final[int] = 1
RUN_SENTINEL_SCHEMA_VERSION: Final[int] = 1

# Namespace UUID used to derive deterministic UUIDv5 run_ids in plan-only mode.
# Derived once from a stable DNS-style string so the value is reproducible
# without embedding hand-picked bytes. MUST NEVER CHANGE.
CHAOS_LIBRARIAN_NAMESPACE_UUID: Final[uuid.UUID] = uuid.uuid5(
    uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1"
)
