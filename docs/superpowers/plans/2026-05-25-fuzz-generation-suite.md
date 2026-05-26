# Fuzz Generation Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement lane-aware deterministic fuzz generation with a generated regression suite, public lane metadata, coverage gates, drift checks, and bounded property-based tests.

**Architecture:** Keep `chaos_librarian.generation` as the public facade for CLI and tests. Move lane configuration and internal content/timeline planning into focused helper modules so the generator can stay deterministic while covering more content and timeline surfaces. Contract metadata is updated first because generated scenarios embed `generation.lane` and profile version 2.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, ruamel.yaml, Hypothesis, pytest, ruff, ty, checked-in JSON Schema artifacts.

---

## Source Spec

Implement the reviewed design in
`docs/superpowers/specs/2026-05-25-fuzz-generation-suite-design.md`.

The implementation must preserve these constraints:

- Replay never calls the generator.
- Generated YAML is explicit, deterministic, and validates before write.
- `fuzz-smoke` remains one small materialize-safe scenario.
- `fuzz-regression` becomes lane-specific generation via `--lane`.
- Lane identity is public schema metadata.
- Existing fuzz static budgets remain per scenario.
- Generated fixtures and schemas must not drift.

## File Structure

Modify these existing files:

- `src/chaos_librarian/contract/profiles.py`
  - Add `FuzzLaneName`.
- `src/chaos_librarian/contract/__init__.py`
  - Bump `SCENARIO_SCHEMA_VERSION` from `10` to `11`.
- `src/chaos_librarian/contract/scenario.py`
  - Add `generation.lane`, bump `FUZZ_GENERATION_PROFILE_VERSION`, and validate lane/profile pairs.
- `src/chaos_librarian/cli/commands/generate.py`
  - Add `--lane`, keep smoke default, reject missing regression lane.
- `src/chaos_librarian/generation.py`
  - Keep public API, delegate lane planning, include lane in summary, and run coverage/full-validation gates.
- `tests/contract/test_scenario.py`
  - Update generation metadata tests and scenario version test.
- `tests/contract/test_schema_export.py`
  - Update frozen `profile_version` assertion.
- `tests/test_generation.py`
  - Add lane determinism, profile label ordering, coverage, and fixture drift tests.
- `tests/cli/test_generate.py`
  - Add CLI lane option tests and JSON summary checks.
- `tests/docs/test_documentation.py`
  - Keep lane docs discoverable.
- `docs/contract/cli-reference.md`
  - Document `--lane`.
- `docs/contract/integration-recipes.md`
  - Document lane usage and manifest gates.
- `docs/developer/testing.md`
  - Document deterministic property-test boundaries.
- `docs/specs/chaos-librarian-design.md`
  - Update Fuzz Profile Generation Policy.
- `docs/user/commands.md`
  - Update user-facing command reference.
- `schemas/scenario.schema.json`
  - Regenerate from Pydantic.
- `tests/fixtures/scenarios/*.yaml`
  - Bump top-level `schema_version`.
- `tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml`
  - Regenerate as profile version 2 with `lane: smoke`.
- `tests/fixtures/scenarios/fuzz-regression-seed-456.yaml`
  - Replace with one committed regression lane fixture, recommended `core-fs`.

Create these files:

- `src/chaos_librarian/generation_lanes.py`
  - Lane enum helpers, lane configs, profile label ordering, coverage model, and coverage derivation.
- `src/chaos_librarian/generation_planner.py`
  - Internal content and timeline planning dataclasses and builders.
- `tests/fixtures/fuzz-seeds.yaml`
  - Deterministic seed manifest for smoke and regression lanes.
- `tests/test_generation_properties.py`
  - Bounded Hypothesis tests for generator invariants.

Do not create a public `generate-suite` command in this implementation.

## Task 1: Contract Lane Metadata

**Files:**
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `tests/contract/test_scenario.py`
- Modify: `tests/contract/test_schema_export.py`
- Regenerate: `schemas/scenario.schema.json`
- Modify: `tests/fixtures/scenarios/*.yaml`

- [ ] **Step 1: Write failing contract tests for lane metadata**

Update `_generated_scenario_payload()` in `tests/contract/test_scenario.py` to emit profile version 2 with `lane: smoke`.

```python
def _generated_scenario_payload() -> dict[str, object]:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = ["fuzz-smoke"]
    payload["generation"] = {
        "generator": "chaos-librarian",
        "profile": "fuzz-smoke",
        "lane": "smoke",
        "profile_version": 2,
        "seed": 1,
        "budgets": {
            "works": 3,
            "variants": 4,
            "bundles": 4,
            "assets": 4,
            "sidecars": 8,
            "timeline_events": 12,
        },
    }
    return payload
```

Add these tests near the existing generation metadata tests:

```python
def test_scenario_accepts_fuzz_lane_metadata() -> None:
    scenario = Scenario.model_validate(_generated_scenario_payload())

    assert scenario.generation is not None
    assert scenario.generation.lane.value == "smoke"


def test_generation_lane_must_match_profile() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    generation["lane"] = "media-rewrite"

    with pytest.raises(ValidationError, match=r"generation\.lane"):
        Scenario.model_validate(payload)


def test_generation_lane_is_required() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    del generation["lane"]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)
```

Update `test_generation_profile_version_must_be_supported()` so version `1` is rejected, because version `2` is now supported:

```python
def test_generation_profile_version_must_be_supported() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    generation["profile_version"] = 1

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)
```

Update `tests/contract/test_schema_export.py`:

```python
def test_scenario_schema_freezes_generation_profile_version() -> None:
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    scenario_schema = json.loads((schemas_dir / "scenario.schema.json").read_text())
    profile_version = scenario_schema["$defs"]["ScenarioGeneration"]["properties"][
        "profile_version"
    ]

    assert profile_version["const"] == 2
    assert "minimum" not in profile_version
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
uv run pytest tests/contract/test_scenario.py::test_scenario_accepts_fuzz_lane_metadata tests/contract/test_scenario.py::test_generation_lane_must_match_profile tests/contract/test_scenario.py::test_generation_lane_is_required -q --no-cov
```

Expected: failures because `ScenarioGeneration` has no `lane` field and still freezes `profile_version` at `1`.

- [ ] **Step 3: Implement contract fields and validation**

In `src/chaos_librarian/contract/profiles.py`, add:

```python
class FuzzLaneName(enum.StrEnum):
    SMOKE = "smoke"
    CORE_FS = "core-fs"
    MEDIA_REWRITE = "media-rewrite"
    SIDECAR_SUBTITLE = "sidecar-subtitle"
    MALFORMED = "malformed"
    NEGATIVE_ORACLE = "negative-oracle"
    FILESYSTEM_ARTIFACT = "filesystem-artifact"
    NETWORK_LAG = "network-lag"
```

In `src/chaos_librarian/contract/__init__.py`, change:

```python
SCENARIO_SCHEMA_VERSION: Final = 11
```

In `src/chaos_librarian/contract/scenario.py`:

```python
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName
```

Add the profile/lane map near `FUZZ_GENERATION_BUDGETS`:

```python
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
```

Update `ScenarioGeneration`:

```python
class ScenarioGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: Literal["chaos-librarian"] = "chaos-librarian"
    profile: FuzzProfileName
    lane: FuzzLaneName
    profile_version: Literal[2]
    seed: int = Field(ge=0)
    budgets: GenerationBudget
```

Change:

```python
FUZZ_GENERATION_PROFILE_VERSION: Final = 2
```

In `Scenario._check_generation_metadata()`, add this check before budget validation:

```python
        allowed_lanes = FUZZ_LANES_BY_PROFILE[self.generation.profile]
        if self.generation.lane not in allowed_lanes:
            raise ValueError("generation.lane must match generation.profile")
```

Update the model literal:

```python
schema_version: Literal[11]
```

- [ ] **Step 4: Update fixture schema versions mechanically**

Run:

```bash
perl -0pi -e 's/^schema_version: 10/schema_version: 11/m' tests/fixtures/scenarios/*.yaml tests/fixtures/scenarios/voom-ci/*.yaml tests/fixtures/scenarios/invalid/*.yaml
```

Then update any inline YAML snippets in tests that still contain `schema_version: 10`:

```bash
rg -n "schema_version: 10" tests src docs/user docs/contract docs/specs
```

Replace only current scenario examples and test payload snippets with `schema_version: 11`. Do not rewrite historical sprint specs under `docs/superpowers/specs/`.

- [ ] **Step 5: Update checked-in generated fixtures to contract v2 for this task**

Before the lane planner exists, edit these two files enough to keep sample-scenario validation green:

`tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml`:

```yaml
schema_version: 11
scenario_id: fuzz-smoke-seed-123
seed: 123
duration_scale: short
profiles:
- fuzz-smoke
generation:
  generator: chaos-librarian
  profile: fuzz-smoke
  lane: smoke
  profile_version: 2
```

`tests/fixtures/scenarios/fuzz-regression-seed-456.yaml`:

```yaml
schema_version: 11
scenario_id: fuzz-regression-core-fs-seed-456
seed: 456
duration_scale: short
profiles:
- fuzz-regression
generation:
  generator: chaos-librarian
  profile: fuzz-regression
  lane: core-fs
  profile_version: 2
```

Keep each fixture's existing `budgets`, `library`, `works`, and `timeline` content in place. Task 7 replaces the bytes with generator output.

- [ ] **Step 6: Regenerate scenario schema**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Expected: `schemas/scenario.schema.json` changes. If any other schema changes, inspect the diff and only keep expected changes from type references.

- [ ] **Step 7: Run focused contract checks**

Run:

```bash
uv run pytest tests/contract/test_scenario.py tests/contract/test_schema_export.py tests/contract/test_sample_scenarios.py -q --no-cov
uv run python -m chaos_librarian.schema_export --check
```

Expected: all pass and schema export reports no drift.

- [ ] **Step 8: Commit contract metadata**

```bash
git status --short
git add -u
git add schemas/scenario.schema.json
git commit -m "feat: add fuzz lane metadata"
```

## Task 2: CLI Lane Option

**Files:**
- Modify: `src/chaos_librarian/cli/commands/generate.py`
- Modify: `tests/cli/test_generate.py`

- [ ] **Step 1: Add failing CLI tests**

Update imports in `tests/cli/test_generate.py`:

```python
from chaos_librarian.contract.profiles import FuzzLaneName
```

Add tests:

```python
def test_generate_regression_requires_lane(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-regression", "--seed", "456", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert "--lane is required for fuzz-regression" in result.stdout + result.stderr
    assert not out.exists()


def test_generate_rejects_lane_profile_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--lane",
            "media-rewrite",
            "--seed",
            "123",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 2
    assert "lane media-rewrite is not valid for fuzz-smoke" in result.stdout + result.stderr
    assert not out.exists()
```

Update the existing JSON summary test so it asserts `lane == "smoke"`.

- [ ] **Step 2: Run CLI tests and verify failures**

Run:

```bash
uv run pytest tests/cli/test_generate.py -q --no-cov
```

Expected: failures because `--lane` is not accepted and summaries do not include `lane`.

- [ ] **Step 3: Add lane option and validation**

In `src/chaos_librarian/cli/commands/generate.py`, import `FuzzLaneName` and `FUZZ_LANES_BY_PROFILE`:

```python
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import FUZZ_LANES_BY_PROFILE
```

Change the command signature:

```python
def generate(
    profile: Annotated[FuzzProfileName, typer.Option("--profile")],
    seed: Annotated[int, typer.Option("--seed", min=0)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    lane: Annotated[FuzzLaneName | None, typer.Option("--lane")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
```

Add a local helper:

```python
def _resolve_lane(profile: FuzzProfileName, lane: FuzzLaneName | None) -> FuzzLaneName:
    if profile is FuzzProfileName.FUZZ_SMOKE and lane is None:
        return FuzzLaneName.SMOKE
    if lane is None:
        raise typer.BadParameter("--lane is required for fuzz-regression")
    if lane not in FUZZ_LANES_BY_PROFILE[profile]:
        raise typer.BadParameter(f"lane {lane.value} is not valid for {profile.value}")
    return lane
```

Use the resolved lane:

```python
    resolved_lane = _resolve_lane(profile=profile, lane=lane)
    data = generate_scenario_yaml(profile=profile, lane=resolved_lane, seed=seed)
```

- [ ] **Step 4: Update public generator signature enough for CLI tests**

Temporarily update `generate_scenario_yaml()` and `generated_scenario_summary()` signatures in `src/chaos_librarian/generation.py` to accept and serialize lane. This is the minimal adapter before the full planner rewrite:

```python
def generate_scenario_yaml(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None = None,
) -> bytes:
    """Return deterministic scenario YAML bytes for one fuzz profile, lane, and seed."""
```

Inside, default smoke lane:

```python
    resolved_lane = lane or FuzzLaneName.SMOKE
```

Update `scenario_id` and `generation`:

```python
        "scenario_id": f"{profile.value}-{resolved_lane.value}-seed-{seed}",
```

```python
            "lane": resolved_lane.value,
```

Update summary:

```python
        "lane": scenario.generation.lane.value,
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest tests/cli/test_generate.py tests/test_generation.py -q --no-cov
```

Expected: all pass after adjusting tests for new scenario IDs:

- smoke ID: `fuzz-smoke-smoke-seed-123`
- regression ID: `fuzz-regression-core-fs-seed-456`

- [ ] **Step 6: Commit CLI lane option**

```bash
git add src/chaos_librarian/cli/commands/generate.py src/chaos_librarian/generation.py tests/cli/test_generate.py tests/test_generation.py
git commit -m "feat: add fuzz generate lane option"
```

## Task 3: Lane Configuration And Coverage Model

**Files:**
- Create: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: `tests/test_generation.py`

- [ ] **Step 1: Add failing tests for lane configs and profile ordering**

In `tests/test_generation.py`, add:

```python
from chaos_librarian.contract.profiles import FuzzLaneName, ProfileName
from chaos_librarian.generation_lanes import lane_config_for, profiles_for_lane
```

Add tests:

```python
def test_profiles_for_lane_orders_fuzz_profile_first() -> None:
    profiles = profiles_for_lane(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
    )

    assert profiles == (
        ProfileName.FUZZ_REGRESSION,
        ProfileName.MALFORMED_MEDIA,
    )


def test_lane_config_rejects_profile_mismatch() -> None:
    with pytest.raises(ValueError, match="not valid"):
        lane_config_for(
            profile=FuzzProfileName.FUZZ_SMOKE,
            lane=FuzzLaneName.MEDIA_REWRITE,
        )


```

- [ ] **Step 2: Run tests and verify import failures**

Run:

```bash
uv run pytest tests/test_generation.py::test_profiles_for_lane_orders_fuzz_profile_first tests/test_generation.py::test_lane_config_rejects_profile_mismatch -q --no-cov
```

Expected: import failure because `generation_lanes.py` does not exist.

- [ ] **Step 3: Implement lane config module**

Create `src/chaos_librarian/generation_lanes.py`:

```python
"""Lane configuration and coverage helpers for deterministic fuzz generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import TimelineActionName


@dataclass(frozen=True, slots=True)
class LaneConfig:
    profile: FuzzProfileName
    lane: FuzzLaneName
    profiles: tuple[ProfileName, ...]
    works: int
    timeline_events: int
    required_cells: frozenset[str]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    cells: frozenset[str]

    def missing_required_cells(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.cells
```

Define cells and configs:

```python
CELL_ACTION_PREFIX: Final = "action:"
CELL_SIDE_SUBTITLE: Final = "sidecar:subtitle"
CELL_SIDE_NFO_OR_POSTER: Final = "sidecar:nfo-or-poster"
CELL_LAG_EFFECT_PREFIX: Final = "network-lag:"


LANE_CONFIGS: Final[dict[tuple[FuzzProfileName, FuzzLaneName], LaneConfig]] = {
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE): LaneConfig(
        profile=FuzzProfileName.FUZZ_SMOKE,
        lane=FuzzLaneName.SMOKE,
        profiles=(ProfileName.FUZZ_SMOKE,),
        works=3,
        timeline_events=12,
        required_cells=frozenset(
            {
                "action:move_asset",
                "action:rename_file",
                "action:edit_metadata",
                "action:create_sidecar",
                "action:update_sidecar",
            }
        ),
    ),
    # Add all regression lane configs in the same table.
}
```

Complete the table with:

- `core-fs`: works `10`, events `32`, required cells for `move_asset`, `rename_file`, `delete_file`, `add_file`, `archive_file`, `move_between_roots`, `slow_copy_start`, `slow_copy_commit`.
- `media-rewrite`: works `10`, events `32`, required cells for `reencode_video`, `reencode_audio`, `remux_container`, `edit_metadata`.
- `sidecar-subtitle`: works `10`, events `32`, required cells for `create_sidecar`, `update_sidecar`, `remove_sidecar`, `extract_subtitle`, `embed_subtitle`, `sidecar:subtitle`, `sidecar:nfo-or-poster`.
- `malformed`: works `10`, events `24`, profile labels `(FUZZ_REGRESSION, MALFORMED_MEDIA)`, required cells for `corrupt_container_header`, `truncate_file`, `corrupt_packet_range`, `write_invalid_duration_metadata`.
- `negative-oracle`: works `8`, events `16`, profile labels `(FUZZ_REGRESSION, NEGATIVE_ORACLE)`, required cell `action:wrong_oracle_hash`.
- `filesystem-artifact`: works `8`, events `16`, profile labels `(FUZZ_REGRESSION, FILESYSTEM_ARTIFACTS)`, required cell `action:touch_mtime`.
- `network-lag`: works `8`, events `18`, profile labels `(FUZZ_REGRESSION, NETWORK_FS_LAG)`, required cells for `network_lag_start`, `network_lag_commit`, `network-lag:delayed_visibility`, `network-lag:delayed_rename`, `network-lag:held_handle`.

Add functions:

```python
def lane_config_for(profile: FuzzProfileName, lane: FuzzLaneName) -> LaneConfig:
    config = LANE_CONFIGS.get((profile, lane))
    if config is None:
        raise ValueError(f"lane {lane.value} is not valid for {profile.value}")
    return config


def profiles_for_lane(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
) -> tuple[ProfileName, ...]:
    return lane_config_for(profile=profile, lane=lane).profiles
```

Implement `coverage_for_payload()`:

```python
def coverage_for_payload(payload: Mapping[str, object]) -> CoverageReport:
    cells: set[str] = set()
    for event in _timeline_events(payload):
        action = event.get("action")
        if isinstance(action, str):
            cells.add(f"{CELL_ACTION_PREFIX}{action}")
        kind = event.get("kind")
        if action == TimelineActionName.CREATE_SIDECAR.value and isinstance(kind, str):
            if kind == "subtitle":
                cells.add(CELL_SIDE_SUBTITLE)
            elif kind in {"nfo", "poster"}:
                cells.add(CELL_SIDE_NFO_OR_POSTER)
        effect = event.get("effect")
        if action == TimelineActionName.NETWORK_LAG_START.value and isinstance(effect, str):
            cells.add(f"{CELL_LAG_EFFECT_PREFIX}{effect}")
    return CoverageReport(cells=frozenset(cells))


def _timeline_events(payload: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    raw = payload.get("timeline", [])
    if not isinstance(raw, list):
        return ()
    return tuple(event for event in raw if isinstance(event, dict))
```

- [ ] **Step 4: Wire generation facade to configs**

In `src/chaos_librarian/generation.py`:

- Import `FuzzLaneName`, `lane_config_for`, and `profiles_for_lane`.
- Replace `_PROFILE_SHAPES` usage with `LaneConfig.works` and `LaneConfig.timeline_events`.
- Use `profiles_for_lane()` for top-level `profiles`.

Do not add the hard required-coverage gate in this task. The full planner is
still shallow at this point, so enforcing every lane's required cells here would
make `generate_scenario_yaml()` fail for regression lanes until Tasks 4-6 land.
Task 4 adds a failing coverage-gate test first, then implements the gate after
the planner emits required lane events.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_generation.py::test_profiles_for_lane_orders_fuzz_profile_first tests/test_generation.py::test_lane_config_rejects_profile_mismatch -q --no-cov
```

Expected: pass.

- [ ] **Step 6: Commit lane configuration**

```bash
git add src/chaos_librarian/generation_lanes.py src/chaos_librarian/generation.py tests/test_generation.py
git commit -m "feat: define fuzz lane coverage"
```

## Task 4: Content And Timeline Planner Foundation

**Files:**
- Create: `src/chaos_librarian/generation_planner.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: `tests/test_generation.py`

- [ ] **Step 1: Add failing tests for deterministic lane coverage**

Add this parametrized test to `tests/test_generation.py`:

```python
from ruamel.yaml import YAML

from chaos_librarian.generation_lanes import coverage_for_payload


def _generated_payload(
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
) -> dict[str, object]:
    yaml = YAML(typ="safe")
    data = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
    payload = yaml.load(data.decode())
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize(
    ("profile", "lane", "seed"),
    [
        (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 123),
    ],
)
def test_generated_lane_meets_required_coverage(
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
) -> None:
    payload = _generated_payload(profile=profile, lane=lane, seed=seed)
    config = lane_config_for(profile=profile, lane=lane)

    missing = coverage_for_payload(payload).missing_required_cells(config.required_cells)
    assert missing == frozenset()
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run pytest tests/test_generation.py::test_generated_lane_meets_required_coverage -q --no-cov
```

Expected: failure because smoke generation is still random and does not
guarantee every required smoke coverage cell.

- [ ] **Step 3: Create planner dataclasses and base helpers**

Create `src/chaos_librarian/generation_planner.py`:

```python
"""Content and timeline planning for deterministic fuzz generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.generation_lanes import LaneConfig


@dataclass(frozen=True, slots=True)
class PlannedAsset:
    asset_id: str
    container: str
    video_codec: str
    resolution: str
    audio_channels: str
    has_embedded_subtitle: bool = False


@dataclass(slots=True)
class TimelinePlanner:
    root_id: str
    root_path: str
    secondary_root_id: str
    assets: list[PlannedAsset]
    events: list[dict[str, object]] = field(default_factory=list)
    placed_assets: set[str] = field(default_factory=set)
    sidecars_by_asset: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    deleted_assets: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.placed_assets = {asset.asset_id for asset in self.assets}

    def next_index(self) -> int:
        return len(self.events) + 1

    def event_id(self, prefix: str) -> str:
        return f"fuzz_{self.next_index():04d}_{prefix}"

    def at(self) -> str:
        return f"{self.next_index()}ns"
```

Add `plan_payload_parts()`:

```python
def plan_payload_parts(
    *,
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
    config: LaneConfig,
    rng: Any,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    assets = _planned_assets(config=config, rng=rng)
    library = _library_for_lane(lane)
    planner = TimelinePlanner(
        root_id="movies-hd",
        root_path="movies-hd",
        secondary_root_id="cold-storage",
        assets=assets,
    )
    _emit_lane_required_events(planner=planner, lane=lane, rng=rng)
    _fill_remaining_events(planner=planner, config=config, rng=rng)
    return (
        library,
        _works_payload(profile=profile, lane=lane, seed=seed, assets=assets, rng=rng),
        planner.events,
    )
```

- [ ] **Step 4: Implement lane-aware library roots**

Implement `_library_for_lane()` before adding root-moving event emitters:

```python
def _library_for_lane(lane: FuzzLaneName) -> dict[str, object]:
    roots: list[dict[str, str]] = [{"id": "movies-hd", "path": "movies-hd"}]
    library: dict[str, object] = {"roots": roots}
    if lane is FuzzLaneName.CORE_FS:
        roots.append({"id": "cold-storage", "path": "cold-storage"})
        library["archive_root"] = "cold-storage"
    return library
```

`core-fs` must declare both root IDs because its required actions include
`archive_file` and `move_between_roots`. Without these declarations, semantic
validation rejects generated output with `E_ROOT_UNKNOWN` even though the event
shapes are Pydantic-valid.

- [ ] **Step 5: Implement content payload helpers**

Implement `_planned_assets()` so every lane gets deterministic heterogeneous assets:

```python
def _planned_assets(*, config: LaneConfig, rng: Any) -> list[PlannedAsset]:
    containers = ("mkv", "mp4")
    resolutions = ("sd", "hd", "1080p")
    channels = ("mono", "stereo", "5.1")
    assets: list[PlannedAsset] = []
    for index in range(1, config.works + 1):
        assets.append(
            PlannedAsset(
                asset_id=f"asset_{index:03d}",
                container=containers[(index - 1) % len(containers)],
                video_codec="hevc" if index % 5 == 0 else "h264",
                resolution=resolutions[(index - 1) % len(resolutions)],
                audio_channels=channels[(index - 1) % len(channels)],
                has_embedded_subtitle=index % 3 == 0,
            )
        )
    return assets
```

Implement `_works_payload()` with one work, variant, bundle, and asset per planned asset. Include a subtitle track for `has_embedded_subtitle` assets:

```python
def _asset_payload(asset: PlannedAsset, rng: Any) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": asset.asset_id,
        "role": "primary_video",
        "container": asset.container,
        "duration_seconds": rng.randint(2, 8),
        "video": {
            "source": "color_bars",
            "codec": asset.video_codec,
            "resolution": asset.resolution,
        },
        "audio": [
            {
                "source": "sine",
                "codec": "aac",
                "channels": asset.audio_channels,
                "language": "eng",
            }
        ],
    }
    if asset.has_embedded_subtitle:
        payload["subtitles"] = [
            {
                "source": "generated_srt",
                "codec": "srt",
                "language": "eng",
                "mode": "embedded",
            }
        ]
    return payload
```

- [ ] **Step 6: Implement smoke event helpers and filler**

Before wiring the public generator to `plan_payload_parts()`, implement the
minimum safe event helpers that make the smoke lane deterministic:

- `_move_asset`
- `_rename_file`
- `_edit_metadata`
- `_create_nfo_sidecar`
- `_update_first_sidecar`

Each helper must append a Pydantic-valid event shape and use
`planner.event_id()` / `planner.at()` for deterministic IDs and timestamps.
`_create_nfo_sidecar()` must record the created sidecar in
`planner.sidecars_by_asset` and set `"kind": SidecarKind.NFO.value`.
`_update_first_sidecar()` must use a recorded sidecar path so semantic
validation does not emit `E_SIDECAR_TARGET_UNKNOWN`.

Implement `_emit_lane_required_events()` with a smoke branch first:

```python
def _emit_lane_required_events(
    *,
    planner: TimelinePlanner,
    lane: FuzzLaneName,
    rng: Any,
) -> None:
    assets = planner.assets
    if lane is FuzzLaneName.SMOKE:
        _move_asset(planner, assets[0])
        _rename_file(planner, assets[1])
        _edit_metadata(planner, assets[0])
        _create_nfo_sidecar(planner, assets[0])
        _update_first_sidecar(planner)
```

Add `_fill_remaining_events()` with simple safe actions until
`config.timeline_events` is reached:

```python
def _fill_remaining_events(
    *,
    planner: TimelinePlanner,
    config: LaneConfig,
    rng: Any,
) -> None:
    safe_actions = (_move_asset, _rename_file, _edit_metadata, _create_nfo_sidecar)
    while len(planner.events) < config.timeline_events:
        action = rng.choice(safe_actions)
        action(planner, rng.choice(planner.assets))
```

Do not emit `delete_file`, `add_file`, slow-copy, media, sidecar-removal, or
profile-gated events in this filler. Tasks 5 and 6 add those lane-specific
required branches.

- [ ] **Step 7: Wire public generator to planner**

In `src/chaos_librarian/generation.py`, replace `_generate_works()` and `_generate_timeline()` calls with:

```python
    config = lane_config_for(profile=profile, lane=resolved_lane)
    library, works, timeline = plan_payload_parts(
        profile=profile,
        lane=resolved_lane,
        seed=seed,
        config=config,
        rng=rng,
    )
```

Use `library`, `works`, and `timeline` in the payload.

- [ ] **Step 8: Add validation and coverage gate tests**

Add these tests to `tests/test_generation.py`:

```python
from dataclasses import replace

import chaos_librarian.generation_lanes as generation_lanes
from chaos_librarian.generation import (
    GeneratedScenarioCoverageError,
    GeneratedScenarioValidationError,
)
```

```python
def test_generate_rejects_missing_required_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    key = (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE)
    config = generation_lanes.LANE_CONFIGS[key]
    monkeypatch.setitem(
        generation_lanes.LANE_CONFIGS,
        key,
        replace(config, required_cells=frozenset({"missing:required-cell"})),
    )

    with pytest.raises(GeneratedScenarioCoverageError, match="missing required coverage"):
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_SMOKE,
            lane=FuzzLaneName.SMOKE,
            seed=123,
        )


def test_generate_rejects_budget_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    key = (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE)
    config = generation_lanes.LANE_CONFIGS[key]
    monkeypatch.setitem(generation_lanes.LANE_CONFIGS, key, replace(config, works=4))

    with pytest.raises(
        GeneratedScenarioValidationError,
        match="generated scenario failed validation",
    ):
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_SMOKE,
            lane=FuzzLaneName.SMOKE,
            seed=123,
        )
```

- [ ] **Step 9: Implement coverage and full-validation gates**

In `src/chaos_librarian/generation.py`, add errors:

```python
class GeneratedScenarioCoverageError(ValueError):
    """Raised when generated YAML does not satisfy the selected lane contract."""


class GeneratedScenarioValidationError(ValueError):
    """Raised when generated YAML fails the full validation pipeline."""
```

After payload construction and before `_dump_yaml()`, run the coverage check:

```python
    coverage = coverage_for_payload(payload)
    missing = coverage.missing_required_cells(config.required_cells)
    if missing:
        missing_sorted = ", ".join(sorted(missing))
        raise GeneratedScenarioCoverageError(
            f"missing required coverage for {profile.value}/{resolved_lane.value} "
            f"seed {seed}: {missing_sorted}"
        )
```

Update `_validate_generated_yaml()` to run the same shape and semantic validation as `validate`:

```python
def _validate_generated_yaml(data: bytes) -> Scenario:
    run_input = prepare_run_input_from_bytes(raw_bytes=data, source_label="<generated>")
    report = run_validation(run_input)
    if not report.ok:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise GeneratedScenarioValidationError(f"generated scenario failed validation: {issues}")
    return run_input.scenario
```

Add imports:

```python
from chaos_librarian.generation_lanes import coverage_for_payload
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation
```

- [ ] **Step 10: Run smoke generation test**

Run:

```bash
uv run pytest \
  tests/test_generation.py::test_generated_yaml_validates_as_scenario \
  tests/test_generation.py::test_generated_lane_meets_required_coverage \
  tests/test_generation.py::test_generate_rejects_missing_required_coverage \
  tests/test_generation.py::test_generate_rejects_budget_overflow \
  -q --no-cov
```

Expected: pass for smoke after basic planner wiring and coverage/full-validation
gates.

- [ ] **Step 11: Commit planner foundation**

```bash
git add src/chaos_librarian/generation.py src/chaos_librarian/generation_planner.py tests/test_generation.py
git commit -m "feat: add fuzz generation planner"
```

## Task 5: Materialize-Safe Lanes

**Files:**
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `tests/test_generation.py`

- [ ] **Step 1: Extend coverage test to materialize-safe lanes**

Update `test_generated_lane_meets_required_coverage()` so its parametrized cases
cover the materialize-safe lane set:

```python
[
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 123),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS, 456),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE, 457),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE, 458),
]
```

Run:

```bash
uv run pytest tests/test_generation.py::test_generated_lane_meets_required_coverage -q --no-cov
```

Expected: the newly added regression safe lanes fail until this task adds their
required event emitters.

- [ ] **Step 2: Implement event emitters for core filesystem lane**

In `generation_planner.py`, reuse the smoke helpers from Task 4 and add the
remaining core-filesystem helpers. The helpers must append these exact event
shapes:

```python
def _move_asset(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("move"),
            "at": planner.at(),
            "action": "move_asset",
            "target": asset.asset_id,
            "to": (
                f"{planner.root_path}/fuzz/"
                f"{asset.asset_id}-{planner.next_index():04d}.{asset.container}"
            ),
        }
    )
```

Implement helpers for:

- `rename_file`
- `delete_file`
- `add_file`
- `archive_file`
- `move_between_roots`
- `slow_copy_start`
- `slow_copy_commit`

Use unique event IDs and paths. For slow copy, emit adjacent start/commit events:

```python
start_id = planner.event_id("slow_copy_start")
planner.events.append(
    {
        "id": start_id,
        "at": planner.at(),
        "action": "slow_copy_start",
        "target": asset.asset_id,
        "to": f"{planner.root_path}/fuzz/{asset.asset_id}-slow.{asset.container}",
        "temp_path": f"{planner.root_path}/fuzz/.{asset.asset_id}-slow.tmp",
        "duration": "2s",
    }
)
planner.events.append(
    {
        "id": planner.event_id("slow_copy_commit"),
        "at": planner.at(),
        "action": "slow_copy_commit",
        "for": start_id,
    }
)
```

For `move_between_roots`, use the declared planner root IDs so semantic
validation can resolve both sides:

```python
def _move_between_roots(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("move_between_roots"),
            "at": planner.at(),
            "action": "move_between_roots",
            "target": asset.asset_id,
            "from_root_id": planner.root_id,
            "to_root_id": planner.secondary_root_id,
        }
    )
```

- [ ] **Step 3: Implement media and sidecar lane emitters**

Add helpers for media actions:

```python
def _reencode_video(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("reencode_video"),
            "at": planner.at(),
            "action": "reencode_video",
            "target": asset.asset_id,
            "resolution": "1080p" if asset.resolution != "1080p" else "hd",
            "codec": "h264",
        }
    )
```

Add helpers for:

- `reencode_audio` with `from_channels` equal to the asset channel and `to_channels` changed to another supported channel.
- `remux_container` with `to_container` changed from the asset container.
- `edit_metadata` with a non-empty `fields` map.

Add sidecar helpers:

- `create_sidecar` subtitle with `kind: subtitle` and `language: eng`.
- `create_sidecar` NFO or poster with no language.
- `update_sidecar`.
- `remove_sidecar`.
- `extract_subtitle` using an asset with `has_embedded_subtitle=True`.
- `embed_subtitle` using the subtitle sidecar path produced by `extract_subtitle`.

Do not let `embed_subtitle` pick the first arbitrary sidecar. If it consumes an
NFO or poster sidecar, semantic validation emits `E_SIDECAR_KIND_MISMATCH`.

- [ ] **Step 4: Fill required lane events**

Implement `_emit_lane_required_events()` with explicit per-lane branches:

```python
def _emit_lane_required_events(
    *,
    planner: TimelinePlanner,
    lane: FuzzLaneName,
    rng: Any,
) -> None:
    assets = planner.assets
    if lane is FuzzLaneName.SMOKE:
        _move_asset(planner, assets[0])
        _rename_file(planner, assets[1])
        _edit_metadata(planner, assets[0])
        _create_nfo_sidecar(planner, assets[0])
        _update_first_sidecar(planner)
    elif lane is FuzzLaneName.CORE_FS:
        _move_asset(planner, assets[0])
        _rename_file(planner, assets[1])
        _delete_file(planner, assets[2])
        _add_file(planner, assets[2])
        _archive_file(planner, assets[3])
        _move_between_roots(planner, assets[4])
        _slow_copy_pair(planner, assets[5])
    elif lane is FuzzLaneName.MEDIA_REWRITE:
        _reencode_video(planner, assets[0])
        _reencode_audio(planner, assets[1])
        _remux_container(planner, assets[2])
        _edit_metadata(planner, assets[3])
    elif lane is FuzzLaneName.SIDECAR_SUBTITLE:
        _create_subtitle_sidecar(planner, assets[0])
        _update_first_sidecar(planner)
        _remove_first_sidecar(planner)
        _create_nfo_sidecar(planner, assets[1])
        _extract_subtitle(planner, _first_embedded_subtitle_asset(assets))
        _embed_latest_subtitle_sidecar(planner)
```

Leave gated lanes for Task 6.

- [ ] **Step 5: Implement weighted filler for safe lanes**

Implement `_fill_remaining_events()` so it appends simple legal actions until `config.timeline_events` is reached:

```python
def _fill_remaining_events(
    *,
    planner: TimelinePlanner,
    config: LaneConfig,
    rng: Any,
) -> None:
    safe_actions = (_move_asset, _rename_file, _edit_metadata, _create_nfo_sidecar)
    while len(planner.events) < config.timeline_events:
        action = rng.choice(safe_actions)
        action(planner, rng.choice(planner.assets))
```

For lanes with pending sidecars, allow `_update_first_sidecar`. Do not emit `delete_file` in filler unless the helper can safely add the asset back.

- [ ] **Step 6: Run coverage and validation tests for safe lanes**

Run:

```bash
uv run pytest tests/test_generation.py::test_generated_lane_meets_required_coverage tests/test_generation.py::test_generated_yaml_validates_as_scenario -q --no-cov
```

Expected: smoke, core-fs, media-rewrite, and sidecar-subtitle pass.

- [ ] **Step 7: Commit materialize-safe lanes**

```bash
git add src/chaos_librarian/generation_planner.py tests/test_generation.py
git commit -m "feat: generate materialize-safe fuzz lanes"
```

## Task 6: Profile-Gated Regression Lanes

**Files:**
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `tests/test_generation.py`

- [ ] **Step 1: Add tests for profile labels on gated lanes**

Extend `test_generated_lane_meets_required_coverage()` so its parametrized cases
also include the gated lanes:

```python
[
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 123),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS, 456),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE, 457),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE, 458),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED, 459),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NEGATIVE_ORACLE, 460),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.FILESYSTEM_ARTIFACT, 461),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NETWORK_LAG, 462),
]
```

Add to `tests/test_generation.py`:

```python
@pytest.mark.parametrize(
    ("lane", "required_profiles"),
    [
        (FuzzLaneName.MALFORMED, ("fuzz-regression", "malformed-media")),
        (FuzzLaneName.NEGATIVE_ORACLE, ("fuzz-regression", "negative-oracle")),
        (FuzzLaneName.FILESYSTEM_ARTIFACT, ("fuzz-regression", "filesystem-artifacts")),
        (FuzzLaneName.NETWORK_LAG, ("fuzz-regression", "network-fs-lag")),
    ],
)
def test_generated_gated_lanes_include_required_profiles(
    lane: FuzzLaneName,
    required_profiles: tuple[str, ...],
) -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=lane,
        seed=459,
    )

    assert tuple(payload["profiles"]) == required_profiles
```

Run:

```bash
uv run pytest tests/test_generation.py::test_generated_lane_meets_required_coverage tests/test_generation.py::test_generated_gated_lanes_include_required_profiles -q --no-cov
```

Expected: gated coverage cases fail until this task adds their required event
emitters. Profile-label assertions should pass once Task 3's lane configs are
wired into generated `profiles`.

- [ ] **Step 2: Implement gated lane event helpers**

In `generation_planner.py`, add:

```python
from chaos_librarian.contract.scenario import NetworkLagEffect
```

Add helpers for:

```python
def _corrupt_container_header(planner: TimelinePlanner, asset: PlannedAsset) -> None:
    planner.events.append(
        {
            "id": planner.event_id("corrupt_header"),
            "at": planner.at(),
            "action": "corrupt_container_header",
            "target": asset.asset_id,
            "bytes": 64,
        }
    )
```

Implement:

- `truncate_file` with `keep_bytes: 4096`.
- `corrupt_packet_range` with `stream: video`, `packet_start: 0`, `packet_count: 1`.
- `write_invalid_duration_metadata` with `value: not-a-duration`.
- `wrong_oracle_hash`.
- `touch_mtime` with `offset: 2s`.
- `network_lag_start` / `network_lag_commit` pairs for `delayed_visibility`, `delayed_rename`, and `held_handle`.

Network lag pairs must use valid `after` references:

```python
trigger_id = planner.event_id("rename_for_lag")
planner.events.append(
    {
        "id": trigger_id,
        "at": planner.at(),
        "action": "rename_file",
        "target": asset.asset_id,
        "to": f"{planner.root_path}/fuzz/{asset.asset_id}-lag.{asset.container}",
    }
)
start_id = planner.event_id("network_lag_start")
planner.events.append(
    {
        "id": start_id,
        "at": planner.at(),
        "action": "network_lag_start",
        "effect": effect.value,
        "target": asset.asset_id,
        "after": trigger_id,
        "duration": "1s",
    }
)
planner.events.append(
    {
        "id": planner.event_id("network_lag_commit"),
        "at": planner.at(),
        "action": "network_lag_commit",
        "for": start_id,
    }
)
```

- [ ] **Step 3: Add gated lane branches**

Extend `_emit_lane_required_events()`:

```python
    elif lane is FuzzLaneName.MALFORMED:
        _corrupt_container_header(planner, assets[0])
        _truncate_file(planner, assets[1])
        _corrupt_packet_range(planner, assets[2])
        _write_invalid_duration_metadata(planner, assets[3])
    elif lane is FuzzLaneName.NEGATIVE_ORACLE:
        _wrong_oracle_hash(planner, assets[0])
    elif lane is FuzzLaneName.FILESYSTEM_ARTIFACT:
        _touch_mtime(planner, assets[0])
    elif lane is FuzzLaneName.NETWORK_LAG:
        _network_lag_pair(planner, assets[0], NetworkLagEffect.DELAYED_VISIBILITY)
        _network_lag_pair(planner, assets[1], NetworkLagEffect.DELAYED_RENAME)
        _network_lag_pair(planner, assets[2], NetworkLagEffect.HELD_HANDLE)
```

- [ ] **Step 4: Run generation suite tests**

Run:

```bash
uv run pytest tests/test_generation.py -q --no-cov
```

Expected: all generation unit tests pass.

- [ ] **Step 5: Commit gated lanes**

```bash
git add src/chaos_librarian/generation_planner.py tests/test_generation.py
git commit -m "feat: generate profile-gated fuzz lanes"
```

## Task 7: Seed Manifest And Fixture Drift

**Files:**
- Create: `tests/fixtures/fuzz-seeds.yaml`
- Modify: `tests/test_generation.py`
- Regenerate: `tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml`
- Regenerate: `tests/fixtures/scenarios/fuzz-regression-seed-456.yaml`

- [ ] **Step 1: Add seed manifest**

Create `tests/fixtures/fuzz-seeds.yaml`:

```yaml
fuzz_smoke:
  - lane: smoke
    seed: 123
    gates: [validate, plan, replay, materialize]
fuzz_regression:
  - lane: core-fs
    seed: 456
    gates: [validate, plan, replay, materialize]
  - lane: media-rewrite
    seed: 457
    gates: [validate, plan, replay, materialize]
  - lane: sidecar-subtitle
    seed: 458
    gates: [validate, plan, replay, materialize]
  - lane: malformed
    seed: 459
    gates: [validate, plan, replay, materialize]
  - lane: negative-oracle
    seed: 460
    gates: [validate, plan, replay, materialize, run]
  - lane: filesystem-artifact
    seed: 461
    gates: [validate, plan, replay, materialize, run]
  - lane: network-lag
    seed: 462
    gates: [validate, plan, replay, run]
```

- [ ] **Step 2: Add seed manifest and fixture drift tests**

In `tests/test_generation.py`, add:

```python
VALID_SEED_MANIFEST_GATES = frozenset(
    {"validate", "plan", "replay", "materialize", "run"}
)


def test_seed_manifest_lists_supported_lanes_and_generates_valid_yaml() -> None:
    manifest_path = Path(__file__).resolve().parent / "fixtures" / "fuzz-seeds.yaml"
    yaml = YAML(typ="safe")
    manifest = yaml.load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)

    cases = _seed_manifest_cases(manifest)
    expected_cases = frozenset(generation_lanes.LANE_CONFIGS)
    assert frozenset((profile, lane) for profile, lane, _, _ in cases) == expected_cases

    for profile, lane, seed, gates in cases:
        assert frozenset(gates) <= VALID_SEED_MANIFEST_GATES
        payload = _generated_payload(profile=profile, lane=lane, seed=seed)
        config = lane_config_for(profile=profile, lane=lane)
        missing = coverage_for_payload(payload).missing_required_cells(config.required_cells)
        assert missing == frozenset()


def _seed_manifest_cases(
    manifest: dict[object, object],
) -> tuple[tuple[FuzzProfileName, FuzzLaneName, int, tuple[str, ...]], ...]:
    cases: list[tuple[FuzzProfileName, FuzzLaneName, int, tuple[str, ...]]] = []
    profile_keys = {
        "fuzz_smoke": FuzzProfileName.FUZZ_SMOKE,
        "fuzz_regression": FuzzProfileName.FUZZ_REGRESSION,
    }
    for key, profile in profile_keys.items():
        entries = manifest.get(key)
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            lane = FuzzLaneName(entry["lane"])
            seed = entry["seed"]
            gates = entry["gates"]
            assert isinstance(seed, int)
            assert isinstance(gates, list)
            cases.append((profile, lane, seed, tuple(str(gate) for gate in gates)))
    return tuple(cases)


def test_committed_generated_fixtures_match_generator() -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "scenarios"
    cases = [
        (
            fixture_dir / "fuzz-smoke-seed-123.yaml",
            FuzzProfileName.FUZZ_SMOKE,
            FuzzLaneName.SMOKE,
            123,
        ),
        (
            fixture_dir / "fuzz-regression-seed-456.yaml",
            FuzzProfileName.FUZZ_REGRESSION,
            FuzzLaneName.CORE_FS,
            456,
        ),
    ]
    for path, profile, lane, seed in cases:
        expected = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
        assert path.read_bytes() == expected
```

- [ ] **Step 3: Regenerate committed generated fixtures**

Run:

```bash
tmpdir="$(mktemp -d)"
uv run chaos-librarian generate --profile fuzz-smoke --seed 123 --out "$tmpdir/fuzz-smoke-seed-123.yaml"
uv run chaos-librarian generate --profile fuzz-regression --lane core-fs --seed 456 --out "$tmpdir/fuzz-regression-seed-456.yaml"
cp "$tmpdir/fuzz-smoke-seed-123.yaml" tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml
cp "$tmpdir/fuzz-regression-seed-456.yaml" tests/fixtures/scenarios/fuzz-regression-seed-456.yaml
```

Check that the generated files contain:

```yaml
schema_version: 11
generation:
  lane: smoke
  profile_version: 2
```

and:

```yaml
schema_version: 11
scenario_id: fuzz-regression-core-fs-seed-456
generation:
  lane: core-fs
  profile_version: 2
```

- [ ] **Step 4: Run sample and drift tests**

Run:

```bash
uv run pytest \
  tests/test_generation.py::test_seed_manifest_lists_supported_lanes_and_generates_valid_yaml \
  tests/test_generation.py::test_committed_generated_fixtures_match_generator \
  tests/contract/test_sample_scenarios.py \
  -q --no-cov
```

Expected: pass.

- [ ] **Step 5: Commit manifest and fixture drift**

```bash
git add tests/fixtures/fuzz-seeds.yaml tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml tests/fixtures/scenarios/fuzz-regression-seed-456.yaml tests/test_generation.py
git commit -m "test: add fuzz seed manifest drift checks"
```

## Task 8: Property-Based Generator Tests

**Files:**
- Create: `tests/test_generation_properties.py`

- [ ] **Step 1: Add property tests**

Create `tests/test_generation_properties.py`:

```python
"""Property tests for deterministic fuzz scenario generation."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import generate_scenario_yaml
from chaos_librarian.generation_lanes import coverage_for_payload, lane_config_for
from chaos_librarian.scenario_io import parse_scenario_bytes


LANE_CASES = (
    (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NEGATIVE_ORACLE),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.FILESYSTEM_ARTIFACT),
    (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NETWORK_LAG),
)


def _parse(data: bytes) -> Scenario:
    raw, _ = parse_scenario_bytes(data, source=Path("<generated-property>"))
    return Scenario.model_validate(raw)


@settings(
    max_examples=64,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(
    case=st.sampled_from(LANE_CASES),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_generated_scenarios_are_deterministic_and_valid(
    case: tuple[FuzzProfileName, FuzzLaneName],
    seed: int,
) -> None:
    profile, lane = case

    first = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
    second = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)

    assert first == second
    scenario = _parse(first)
    assert scenario.generation is not None
    assert scenario.generation.profile is profile
    assert scenario.generation.lane is lane


@settings(max_examples=64, deadline=None)
@given(
    case=st.sampled_from(LANE_CASES),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_generated_scenarios_meet_lane_coverage(
    case: tuple[FuzzProfileName, FuzzLaneName],
    seed: int,
) -> None:
    profile, lane = case
    data = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
    raw, _ = parse_scenario_bytes(data, source=Path("<generated-property>"))
    config = lane_config_for(profile=profile, lane=lane)

    assert coverage_for_payload(raw).missing_required_cells(config.required_cells) == frozenset()
```

- [ ] **Step 2: Run property tests**

Run:

```bash
uv run pytest tests/test_generation_properties.py -q --no-cov
```

Expected: pass. If failures expose a seed-specific lifecycle or coverage bug, fix the generator rather than relaxing the property.

- [ ] **Step 3: Commit property tests**

```bash
git add tests/test_generation_properties.py
git commit -m "test: add fuzz generation properties"
```

## Task 9: Plan/Replay Regression For Generated Lanes

**Files:**
- Modify: `tests/cli/test_replay.py` or create `tests/cli/test_generate_replay.py`

- [ ] **Step 1: Add plan/replay test for a generated lane**

Prefer a new focused file `tests/cli/test_generate_replay.py` if `tests/cli/test_replay.py` is already large.

Add:

```python
"""Replay coverage for generated fuzz lane scenarios."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.generation import generate_scenario_yaml

runner = CliRunner()


def test_generated_regression_lane_plans_and_replays(tmp_path: Path) -> None:
    scenario = tmp_path / "fuzz-regression-core-fs.yaml"
    run_dir = tmp_path / "run"
    replay_dir = tmp_path / "replay"
    scenario.write_bytes(
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_REGRESSION,
            lane=FuzzLaneName.CORE_FS,
            seed=456,
        )
    )

    plan_result = runner.invoke(app, ["plan", str(scenario), "--out", str(run_dir), "--json"])
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr

    replay_result = runner.invoke(
        app,
        ["replay", str(run_dir / "replay.json"), "--out", str(replay_dir), "--json"],
    )
    assert replay_result.exit_code == 0, replay_result.stdout + replay_result.stderr
```

- [ ] **Step 2: Add replay-never-calls-generator guard for lane metadata**

If the existing `tests/cli/test_replay.py::TestReplayCommand::test_generated_fixture_replays_without_calling_generator` still covers this with the smoke fixture, update its expected fixture metadata to profile version 2 and lane. Add a regression-lane variant only if the smoke fixture no longer exercises lane metadata enough.

- [ ] **Step 3: Run CLI replay tests**

Run:

```bash
uv run pytest tests/cli/test_generate_replay.py tests/cli/test_replay.py::TestReplayCommand::test_generated_fixture_replays_without_calling_generator -q --no-cov
```

Expected: pass.

- [ ] **Step 4: Commit plan/replay regression**

```bash
git add tests/cli/test_generate_replay.py tests/cli/test_replay.py
git commit -m "test: cover fuzz lane replay"
```

## Task 10: Documentation Updates

**Files:**
- Modify: `docs/specs/chaos-librarian-design.md`
- Modify: `docs/contract/cli-reference.md`
- Modify: `docs/contract/integration-recipes.md`
- Modify: `docs/developer/testing.md`
- Modify: `docs/user/commands.md`
- Modify: `tests/docs/test_documentation.py`

- [ ] **Step 1: Update CLI docs**

In `docs/contract/cli-reference.md`, update the command list:

```text
chaos-librarian generate --profile fuzz-regression --lane core-fs --seed 456 --out scenario.yaml --json
```

Update the `generate` command description:

```markdown
`generate` writes deterministic fuzz scenario YAML. `--profile` accepts
`fuzz-smoke` or `fuzz-regression`; `--seed` must be a non-negative integer.
`--lane` defaults to `smoke` for `fuzz-smoke` and is required for
`fuzz-regression`. `--out` must point to a new file whose parent directory
already exists.
```

In `docs/user/commands.md`, update the user-facing `generate` command
reference with the same `--lane` rules and one regression lane example:

```text
chaos-librarian generate --profile fuzz-regression --lane core-fs --seed 456 --out scenario.yaml --json
```

- [ ] **Step 2: Update integration recipe**

In `docs/contract/integration-recipes.md`, update the fuzz recipe with a regression lane example:

```bash
uv run chaos-librarian generate \
  --profile fuzz-regression \
  --lane media-rewrite \
  --seed 457 \
  --out fuzz-regression-media-rewrite.yaml \
  --json
```

Add a short lane table matching the design: `smoke`, `core-fs`, `media-rewrite`, `sidecar-subtitle`, `malformed`, `negative-oracle`, `filesystem-artifact`, `network-lag`.

- [ ] **Step 3: Update source design policy**

In `docs/specs/chaos-librarian-design.md`, update Fuzz Profile Generation Policy:

- Scenario v11 metadata includes `generation.lane`.
- `fuzz-regression` is a deterministic lane suite.
- Static budgets are per generated scenario.
- CI must shard or explicitly select lanes.

- [ ] **Step 4: Update testing docs**

In `docs/developer/testing.md`, update Fuzz Profile Generation Testing with:

```markdown
Property-based fuzz generation tests use bounded deterministic Hypothesis
settings and must not depend on wall-clock time or installed media tools unless
marked as integration tests.
```

- [ ] **Step 5: Update docs tests**

In `tests/docs/test_documentation.py`, extend `test_fuzz_profile_generation_docs_are_discoverable()`:

```python
    user_commands = _read(DOCS / "user" / "commands.md")

    assert "`core-fs`" in source_design
    assert "--lane media-rewrite" in integration_recipes
    assert "--lane core-fs" in user_commands
    assert "Property-based fuzz generation tests use bounded deterministic" in testing
```

- [ ] **Step 6: Run docs tests**

Run:

```bash
uv run pytest tests/docs -q --no-cov
```

Expected: pass.

- [ ] **Step 7: Commit docs updates**

```bash
git add docs/specs/chaos-librarian-design.md docs/contract/cli-reference.md docs/contract/integration-recipes.md docs/developer/testing.md docs/user/commands.md tests/docs/test_documentation.py
git commit -m "docs: document fuzz generation lanes"
```

## Task 11: Final Verification And Cleanup

**Files:**
- All touched files.

- [ ] **Step 1: Run focused generation and contract suite**

Run:

```bash
uv run pytest \
  tests/test_generation.py \
  tests/test_generation_properties.py \
  tests/contract/test_scenario.py \
  tests/contract/test_schema_export.py \
  tests/contract/test_sample_scenarios.py \
  tests/cli/test_generate.py \
  tests/cli/test_generate_replay.py \
  tests/cli/test_replay.py::TestReplayCommand::test_generated_fixture_replays_without_calling_generator \
  -q --no-cov
```

Expected: all pass.

- [ ] **Step 2: Run schema drift gate**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
```

Expected: exits 0 with no drift.

- [ ] **Step 3: Run lint, format check, and types**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

Expected: all pass with zero warnings.

- [ ] **Step 4: Run docs tests**

Run:

```bash
uv run pytest tests/docs -q --no-cov
```

Expected: all pass.

- [ ] **Step 5: Inspect final diff for scope**

Run:

```bash
git diff --stat origin/main...HEAD
git diff --name-only origin/main...HEAD
```

Expected touched files match this plan. If unrelated files changed, inspect and remove unrelated edits without reverting user work.

- [ ] **Step 6: Final commit if verification changed files**

If formatting or schema regeneration changed files after the previous commits, inspect and stage the
tracked changes:

```bash
git status --short
git add -u
git commit -m "chore: finalize fuzz generation suite"
```

If no files changed, do not create an empty commit.
