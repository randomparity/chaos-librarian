# Issue 97 VOOM CI Fixture Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a stable VOOM-focused CI scenario pack with documented consumer assertions and capability-gated tests.

**Architecture:** Add only fixture YAML, documentation, and tests. Scenario models, schemas, CLI behavior, and materializer behavior stay unchanged. Real-tool tests use existing capability detection so missing optional HEVC support skips only HEVC coverage.

**Tech Stack:** Python 3.13, pytest, ruamel.yaml, Pydantic scenario models, existing materializer/run helpers.

---

## File Structure

- Create `tests/fixtures/scenarios/voom-ci/` containing the five stable pack fixtures.
- Create `tests/contract/test_voom_ci_pack.py` to pin fixture names and structural validity.
- Create `tests/integration/test_voom_ci_pack_real.py` to materialize/run the pack behind capability gates.
- Modify `docs/contract/integration-recipes.md` with the consumer-facing pack table.
- Modify `tests/docs/test_documentation.py` with a discoverability test for the new docs section.

### Task 1: Add Failing Contract And Docs Tests

**Files:**
- Create: `tests/contract/test_voom_ci_pack.py`
- Modify: `tests/docs/test_documentation.py`

- [ ] **Step 1: Write the failing pack contract test**

```python
"""Contract tests for the VOOM-focused CI scenario pack."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.scenario import Scenario

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios" / "voom-ci"

EXPECTED_FIXTURES = (
    "h264-transcode-candidate.yaml",
    "hevc-noop.yaml",
    "malformed-media-header.yaml",
    "single-step-media-mutation.yaml",
    "static-library-baseline.yaml",
)


def _load_yaml(path: Path) -> object:
    yaml = YAML(typ="safe")
    return yaml.load(path.read_text(encoding="utf-8"))


def test_voom_ci_pack_file_list_is_stable() -> None:
    found = tuple(path.name for path in sorted(FIXTURE_DIR.glob("*.yaml")))

    assert found == EXPECTED_FIXTURES


@pytest.mark.parametrize("fixture_name", EXPECTED_FIXTURES)
def test_voom_ci_pack_scenario_validates(fixture_name: str) -> None:
    scenario = Scenario.model_validate(_load_yaml(FIXTURE_DIR / fixture_name))

    assert scenario.scenario_id == f"voom-ci-{Path(fixture_name).stem}"
```

- [ ] **Step 2: Add the failing documentation discoverability test**

Append this test to `tests/docs/test_documentation.py`:

```python
def test_voom_ci_pack_docs_are_discoverable() -> None:
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")

    required_snippets = [
        "VOOM CI Scenario Pack",
        "tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml",
        "tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml",
        "tests/fixtures/scenarios/voom-ci/hevc-noop.yaml",
        "tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml",
        "tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml",
        "ready_for.materialize_static",
        "ready_for.materialize_hevc_video",
        "ready_for.materialize_media_mutations",
        "materialized `step` is plan-only",
    ]
    for snippet in required_snippets:
        assert snippet in integration_recipes
```

- [ ] **Step 3: Run tests to verify they fail for the missing pack/docs**

Run:

```bash
uv run pytest tests/contract/test_voom_ci_pack.py tests/docs/test_documentation.py -q --no-cov
```

Expected: fail because `tests/fixtures/scenarios/voom-ci/*.yaml` and the docs
section do not exist yet.

### Task 2: Add Fixtures And Consumer Documentation

**Files:**
- Create: five `tests/fixtures/scenarios/voom-ci/*.yaml` files
- Modify: `docs/contract/integration-recipes.md`

- [ ] **Step 1: Add `static-library-baseline.yaml`**

Create `tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml`:

```yaml
schema_version: 10
scenario_id: voom-ci-static-library-baseline
seed: 9701
duration_scale: short
library:
  roots:
    - id: root_movies
      path: movies
works:
  - id: work_baseline_movie
    title: VOOM CI Baseline Movie
    variants:
      - id: variant_h264_mp4
        label: h264-mp4
        bundle:
          id: bundle_h264_mp4
          assets:
            - id: asset_baseline_mp4
              role: primary_video
              container: mp4
              duration_seconds: 2
              video:
                source: solid_color
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
      - id: variant_h264_mkv
        label: h264-mkv
        bundle:
          id: bundle_h264_mkv
          assets:
            - id: asset_baseline_mkv
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: channel_tones
                  codec: aac
                  channels: "5.1"
                  language: eng
      - id: variant_sidecar
        label: subtitle-sidecar
        bundle:
          id: bundle_sidecar
          assets:
            - id: asset_baseline_sidecar
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: mandelbrot
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: mono
                  language: eng
              subtitles:
                - source: generated_srt
                  codec: srt
                  language: eng
                  mode: sidecar
timeline: []
```

- [ ] **Step 2: Add `h264-transcode-candidate.yaml`**

Create `tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml`:

```yaml
schema_version: 10
scenario_id: voom-ci-h264-transcode-candidate
seed: 9702
duration_scale: short
library:
  roots:
    - id: root_movies
      path: movies
works:
  - id: work_h264_policy
    title: VOOM CI H264 Policy Candidates
    variants:
      - id: variant_candidate_mp4
        label: h264-mp4
        bundle:
          id: bundle_candidate_mp4
          assets:
            - id: asset_h264_mp4
              role: primary_video
              container: mp4
              duration_seconds: 2
              video:
                source: color_bars
                codec: h264
                resolution: 1080p
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
      - id: variant_candidate_mkv
        label: h264-mkv
        bundle:
          id: bundle_candidate_mkv
          assets:
            - id: asset_h264_mkv
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: solid_color
                codec: h264
                resolution: 1080p
              audio:
                - source: channel_tones
                  codec: aac
                  channels: "5.1"
                  language: eng
timeline: []
```

- [ ] **Step 3: Add `hevc-noop.yaml`**

Create `tests/fixtures/scenarios/voom-ci/hevc-noop.yaml`:

```yaml
schema_version: 10
scenario_id: voom-ci-hevc-noop
seed: 9703
duration_scale: short
library:
  roots:
    - id: root_movies
      path: movies
works:
  - id: work_hevc_noop
    title: VOOM CI HEVC No-Op
    variants:
      - id: variant_hevc_mkv
        label: hevc-mkv
        bundle:
          id: bundle_hevc_mkv
          assets:
            - id: asset_hevc_mkv
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: color_bars
                codec: hevc
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
timeline: []
```

- [ ] **Step 4: Add `single-step-media-mutation.yaml`**

Create `tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml`:

```yaml
schema_version: 10
scenario_id: voom-ci-single-step-media-mutation
seed: 9704
duration_scale: short
library:
  roots:
    - id: root_movies
      path: movies
works:
  - id: work_mutation
    title: VOOM CI Single-Step Mutation
    variants:
      - id: variant_mutation
        label: h264-mkv
        bundle:
          id: bundle_mutation
          assets:
            - id: asset_mutation_main
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: color_bars
                codec: h264
                resolution: 1080p
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
timeline:
  - id: reencode_video_001
    at: 1s
    action: reencode_video
    target: asset_mutation_main
    resolution: hd
    codec: h264
```

- [ ] **Step 5: Add `malformed-media-header.yaml`**

Create `tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml`:

```yaml
schema_version: 10
scenario_id: voom-ci-malformed-media-header
seed: 9705
duration_scale: short
profiles:
  - malformed-media
library:
  roots:
    - id: root_movies
      path: movies
works:
  - id: work_malformed
    title: VOOM CI Malformed Header
    variants:
      - id: variant_malformed
        label: h264-mkv
        bundle:
          id: bundle_malformed
          assets:
            - id: asset_malformed_main
              role: primary_video
              container: mkv
              duration_seconds: 2
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
timeline:
  - id: corrupt_header_001
    at: 1s
    action: corrupt_container_header
    target: asset_malformed_main
    bytes: 64
```

- [ ] **Step 6: Document the pack**

Add this section to `docs/contract/integration-recipes.md` before `Duplicate
And Variant Pack`:

```markdown
## VOOM CI Scenario Pack

The `tests/fixtures/scenarios/voom-ci/` pack gives consumer CI a stable set of
small fixtures that map to common scanner, prober, transcode policy, rescan,
and malformed-media checks. The fixtures stay consumer-neutral; VOOM-specific
exporters still own application database reads and policy assertions.

| Fixture | Consumer assertion | Command | Capability gate |
| --- | --- | --- | --- |
| `tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml` | Scanner/prober final state contains H.264 MP4, H.264 MKV, audio layout, and sidecar subtitle evidence. | `materialize` then `compare --mode final-state` | `ready_for.materialize_static` |
| `tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml` | HEVC policy can select H.264 MP4 and MKV inputs as transcode candidates. | `materialize` then consumer policy execution | `ready_for.materialize_static` |
| `tests/fixtures/scenarios/voom-ci/hevc-noop.yaml` | The same HEVC policy treats an HEVC MKV input as already compliant. | `materialize` then consumer policy execution | `ready_for.materialize_hevc_video` |
| `tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml` | A single deterministic reencode changes final probe/hash evidence for rescan loops. | `run --duration 2s --speed 20x` for live watchers, or `plan`/`step` for oracle-only stepping | `ready_for.materialize_media_mutations` |
| `tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml` | Malformed-media handling reports stable corruption metadata and expected adapter guidance. | `materialize` then inspect `materialization.json.corruption_actions[]` | `ready_for.materialize_media_mutations` |

Check gates with:

```bash
uv run chaos-librarian capabilities --json
```

The malformed fixture opts into the `malformed-media` profile in its YAML. There
is no separate `ready_for` field for that profile.

For mutation loops, materialized `step` is plan-only and rejects `materialize`
or `run` directories with `E_STEP_UNSUPPORTED_MODE`. Use `run` when the
consumer needs live filesystem changes, and use `plan` plus `step` only when a
test needs deterministic oracle snapshots without on-disk media.
```

- [ ] **Step 7: Run contract/docs tests to verify green**

Run:

```bash
uv run pytest tests/contract/test_voom_ci_pack.py tests/docs/test_documentation.py -q --no-cov
```

Expected: pass.

### Task 3: Add Real-Tool Integration Coverage

**Files:**
- Create: `tests/integration/test_voom_ci_pack_real.py`

- [ ] **Step 1: Write the failing integration tests**

```python
"""Real-tool coverage for the VOOM CI scenario pack."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities
from chaos_librarian.materializer.wall_clock import run_wall_clock_scenario
from tests.integration.conftest import _load_materialization_report

PACK_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios" / "voom-ci"
CapabilityName = Literal[
    "materialize_static",
    "materialize_hevc_video",
    "materialize_media_mutations",
]

MATERIALIZE_CASES = (
    ("static-library-baseline.yaml", "materialize_static"),
    ("h264-transcode-candidate.yaml", "materialize_static"),
    ("hevc-noop.yaml", "materialize_hevc_video"),
    ("single-step-media-mutation.yaml", "materialize_media_mutations"),
    ("malformed-media-header.yaml", "materialize_media_mutations"),
)


def _is_ready(field_name: CapabilityName) -> bool:
    caps = detect_capabilities()
    match field_name:
        case "materialize_static":
            return caps.ready_for.materialize_static
        case "materialize_hevc_video":
            return caps.ready_for.materialize_hevc_video
        case "materialize_media_mutations":
            return caps.ready_for.materialize_media_mutations


def _skip_unless_ready(field_name: CapabilityName) -> None:
    if _is_ready(field_name):
        return
    pytest.skip(f"requires capabilities.ready_for.{field_name}")


@pytest.mark.parametrize(("fixture_name", "capability"), MATERIALIZE_CASES)
def test_voom_ci_fixture_materializes(
    fixture_name: str,
    capability: CapabilityName,
    tmp_path: Path,
) -> None:
    _skip_unless_ready(capability)

    out_dir = tmp_path / Path(fixture_name).stem
    artifacts = materialize_scenario(PACK_DIR / fixture_name, out_dir)
    report = _load_materialization_report(out_dir)

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    assert report.outcome is Outcome.SUCCESS
    if fixture_name == "malformed-media-header.yaml":
        assert len(report.corruption_actions) == 1
        assert report.corruption_actions[0].event_id == "corrupt_header_001"
        assert report.corruption_actions[0].target_asset_id == "asset_malformed_main"


def test_voom_ci_single_step_mutation_runs_for_live_rescan(tmp_path: Path) -> None:
    _skip_unless_ready("materialize_media_mutations")

    out_dir = tmp_path / "run-single-step-media-mutation"
    artifacts = run_wall_clock_scenario(
        PACK_DIR / "single-step-media-mutation.yaml",
        out_dir,
        duration="2s",
        speed="20x",
    )

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    assert artifacts.replay_bundle.applied_events == 1
    assert _load_materialization_report(out_dir).outcome is Outcome.SUCCESS
```

- [ ] **Step 2: Run integration tests**

Run:

```bash
uv run pytest tests/integration/test_voom_ci_pack_real.py -q --no-cov
```

Expected: pass on an equipped runner, otherwise skip individual cases based on
the exact missing `ready_for` field.

### Task 4: Verify CLI Acceptance Criteria

**Files:**
- No new files

- [ ] **Step 1: Validate every pack fixture**

Run each command:

```bash
uv run chaos-librarian validate tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml --json
uv run chaos-librarian validate tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml --json
uv run chaos-librarian validate tests/fixtures/scenarios/voom-ci/hevc-noop.yaml --json
uv run chaos-librarian validate tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml --json
uv run chaos-librarian validate tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml --json
```

Expected: each command exits 0 with `"ok": true`.

- [ ] **Step 2: Materialize every pack fixture**

Run each command with fresh temporary output directories:

```bash
uv run chaos-librarian materialize tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml --out /tmp/chaos-issue97-static --json
uv run chaos-librarian materialize tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml --out /tmp/chaos-issue97-h264 --json
uv run chaos-librarian materialize tests/fixtures/scenarios/voom-ci/hevc-noop.yaml --out /tmp/chaos-issue97-hevc --json
uv run chaos-librarian materialize tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml --out /tmp/chaos-issue97-mutation --json
uv run chaos-librarian materialize tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml --out /tmp/chaos-issue97-malformed --json
```

Expected: each command exits 0 with `"ok": true`.

- [ ] **Step 3: Run the live mutation fixture**

Run:

```bash
uv run chaos-librarian run tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml --out /tmp/chaos-issue97-run --duration 2s --speed 20x --json
```

Expected: command exits 0 with `"ok": true` and `"applied_events": 1`.

- [ ] **Step 4: Clean up temporary run directories**

Run:

```bash
trash /tmp/chaos-issue97-static
trash /tmp/chaos-issue97-h264
trash /tmp/chaos-issue97-hevc
trash /tmp/chaos-issue97-mutation
trash /tmp/chaos-issue97-malformed
trash /tmp/chaos-issue97-run
```

### Task 5: Final Verification And Commit

**Files:**
- All modified files

- [ ] **Step 1: Run focused checks**

```bash
uv run pytest tests/contract/test_voom_ci_pack.py tests/docs/test_documentation.py tests/integration/test_voom_ci_pack_real.py -q --no-cov
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Run schema drift gate**

```bash
uv run python -m chaos_librarian.schema_export --check
```

Expected: exits 0 with no schema drift.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add docs/contract/integration-recipes.md tests/contract/test_voom_ci_pack.py tests/docs/test_documentation.py tests/fixtures/scenarios/voom-ci tests/integration/test_voom_ci_pack_real.py
git commit -m "feat: add voom ci scenario pack"
```
