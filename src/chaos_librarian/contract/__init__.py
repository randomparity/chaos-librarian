"""Schema source-of-truth: Pydantic v2 models exported as JSON Schema."""

from __future__ import annotations

import uuid
from typing import Final

# Schema versions. Bumps are always breaking (no minor versions).
# See docs/specs/chaos-librarian-design.md "Versioning".
# Declared as bare ``Final`` (no explicit ``[int]``) so ty infers each value
# as its concrete ``Literal[N]``. That lets test code pass the named constant
# without a type error. Models hardcode the literal (``schema_version:
# Literal[1]`` or ``Literal[2]``) rather than referencing the constant —
# ``ty`` rejects indirect ``Literal[]`` forms. The test in
# test_contract_constants.py asserts ``isinstance(v, int)``.
SCENARIO_SCHEMA_VERSION: Final = 19
MANIFEST_SCHEMA_VERSION: Final = 8
JOURNAL_SCHEMA_VERSION: Final = 1
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 10
VALIDATION_SCHEMA_VERSION: Final = 1
MATERIALIZATION_SCHEMA_VERSION: Final = 12
RUN_SENTINEL_SCHEMA_VERSION: Final = 2
ASSET_REPORT_SCHEMA_VERSION: Final = 8
VARIANT_REPORT_SCHEMA_VERSION: Final = 2
BUNDLE_REPORT_SCHEMA_VERSION: Final = 1
MOVIE_REPORT_SCHEMA_VERSION: Final = 1
SERIES_REPORT_SCHEMA_VERSION: Final = 1
SEASON_REPORT_SCHEMA_VERSION: Final = 1
EPISODE_REPORT_SCHEMA_VERSION: Final = 1
ARTIST_REPORT_SCHEMA_VERSION: Final = 1
ALBUM_REPORT_SCHEMA_VERSION: Final = 1
DISC_REPORT_SCHEMA_VERSION: Final = 1
TRACK_REPORT_SCHEMA_VERSION: Final = 1
CAPABILITIES_SCHEMA_VERSION: Final = 6
OBSERVED_STATE_SCHEMA_VERSION: Final = 3
DIVERGENCE_SCHEMA_VERSION: Final = 1

# Namespace UUID used to derive deterministic UUIDv5 run_ids in plan-only mode.
# Derived once from a stable DNS-style string so the value is reproducible
# without embedding hand-picked bytes. MUST NEVER CHANGE.
CHAOS_LIBRARIAN_NAMESPACE_UUID: Final[uuid.UUID] = uuid.uuid5(
    uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1"
)
