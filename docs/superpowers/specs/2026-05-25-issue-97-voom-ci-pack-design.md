# Issue 97 VOOM CI Fixture Pack Design

## Problem

VOOM has local CI scenarios that mirror Chaos Librarian capabilities, but the
upstream fixture catalog does not expose a small, stable pack for those consumer
checks. Downstream tests must either pin unrelated top-level smoke fixtures or
carry VOOM-owned scenario YAML. Issue #97 asks for an upstream fixture pack that
covers scanner/prober baseline, HEVC policy fixtures, deterministic mutation
rescan, and malformed-media handling.

## Goals

- Add a dedicated `tests/fixtures/scenarios/voom-ci/` pack with stable file
  names that downstream CI can pin directly.
- Keep every fixture small, deterministic, and executable by `materialize` or
  `run` on a standard equipped CI image.
- Document the intended consumer assertion and required capability field for
  each fixture.
- Test that the pack remains present, structurally valid, and materializable
  where the local toolchain supports it.

## Non-Goals

- Do not add VOOM-specific database schema, policy code, or exporter logic.
- Do not change JSON Schema artifacts or scenario model shape.
- Do not add materialized `step` support. PR #102 made `step` explicitly
  plan-only with `E_STEP_UNSUPPORTED_MODE`. The mutation fixture will document
  `run` for live filesystem rescan loops and `plan`/`step` only for oracle-only
  stepping.
- Do not move or rename existing top-level fixtures.

## Approaches Considered

1. **Dedicated `voom-ci` pack under `tests/fixtures/scenarios/`.**
   This is the recommended approach. It gives consumers stable paths, avoids
   overloading general smoke fixtures with VOOM intent, and keeps issue #97
   isolated to fixtures/docs/tests.
2. **Document existing top-level fixtures as the VOOM pack.**
   This avoids duplicated YAML, but the names are not VOOM-focused and some
   fixtures include broader sprint smoke-test intent. Downstream pinning remains
   coupled to unrelated regression fixtures.
3. **Add a generator profile for VOOM CI.**
   This would produce deterministic YAML, but it adds behavior and CLI surface
   for a static, five-fixture need. The issue asks for a small fixture pack, not
   another generation mode.

## Fixture Pack

Create these files:

| File | Purpose | Required capability |
| --- | --- | --- |
| `static-library-baseline.yaml` | Scanner/prober final-state baseline with H.264 MP4, H.264 MKV, and sidecar subtitle coverage. | `ready_for.materialize_static` |
| `h264-transcode-candidate.yaml` | H.264 MP4 and MKV assets that a VOOM HEVC policy can select for transcoding. | `ready_for.materialize_static` |
| `hevc-noop.yaml` | HEVC MKV asset expected to be a no-op under the same HEVC policy. | `ready_for.materialize_hevc_video` |
| `single-step-media-mutation.yaml` | One `reencode_video` event for deterministic rescan and final-state comparison. | `ready_for.materialize_media_mutations` |
| `malformed-media-header.yaml` | One deterministic `corrupt_container_header` event with corruption evidence. | `ready_for.materialize_media_mutations` |

The malformed fixture also requires the scenario-level `malformed-media`
profile opt-in. That profile is selected by the scenario YAML, not by a
separate capabilities field.

## Documentation

Add a `VOOM CI Scenario Pack` section to
`docs/contract/integration-recipes.md`. The section will list every fixture,
the intended consumer assertion, the recommended command, and the capability
gate a downstream CI job should check before running it.

The docs must be consumer-facing but still neutral: say what the fixture proves
for scanner/prober/transcode/no-op/mutation/malformed-media behavior, without
describing VOOM tables or application internals.

## Tests

Add contract tests for the pack:

- The exact file list is stable.
- Every pack scenario validates through `Scenario.model_validate`.
- The docs mention each pack fixture and each optional capability gate.

Add real-tool integration tests gated by existing capability detection. The
gates must be per fixture: static H.264 fixtures require
`ready_for.materialize_static`, HEVC fixtures require
`ready_for.materialize_hevc_video`, and mutation/malformed fixtures require
`ready_for.materialize_media_mutations`. A runner without HEVC support must
skip only HEVC coverage, not the entire pack.

- Materialize all static, HEVC, mutation, and malformed pack fixtures.
- Run the single-step media mutation fixture in wall-clock mode so CI proves it
  can support a live rescan workflow without relying on materialized `step`.

## Success Criteria

- `uv run pytest tests/contract/test_voom_ci_pack.py tests/docs/test_documentation.py -q --no-cov`
  passes.
- `uv run pytest tests/integration/test_voom_ci_pack_real.py -q --no-cov`
  passes on an equipped runner and skips visibly if the required tools are
  absent.
- `uv run chaos-librarian validate` succeeds for every pack fixture.
- `uv run chaos-librarian materialize` succeeds for each pack fixture on this
  equipped development machine.
- `uv run chaos-librarian run` succeeds for
  `single-step-media-mutation.yaml` with a short accelerated duration.
