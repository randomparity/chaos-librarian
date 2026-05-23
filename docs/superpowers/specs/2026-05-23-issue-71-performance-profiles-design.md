# Issue #71 - Larger Performance Profiles

**Status:** design for future implementation.
**GitHub issue:** [#71](https://github.com/randomparity/chaos-librarian/issues/71)
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Media Diversity Goals" and "Sprint 10 - Extended Profiles").
**Target implementation branch:** `feat/issue-71-performance-profiles`.

## Goal

Define the larger performance-profile policy before any long-running or
large-library scenarios are added.

This design closes the issue by specifying:

1. Reserved performance profile labels.
2. Maximum library sizes and generated fixture budgets for each profile.
3. Capability skip rules.
4. CI tiers and ownership.

It does not add new scenario profile enum values, fixtures, generator code, or CI
jobs. The current contract still rejects unknown `profiles` values until an
implementation PR explicitly adds them.

## Context

The default first scenario pack must stay small enough for regular development:
`docs/specs/chaos-librarian-design.md` caps that pack at 50 MB of materialized
output. Sprint 10's extended-profile list includes larger performance profiles,
but the Sprint 10 foundation intentionally shipped only the malformed-media lane.

Without explicit budgets, future performance fixtures could make regular PR CI
slow, hide capability skips, or produce run directories too large for a developer
machine. The profile contract must define those limits before profile scenarios
exist.

## Profile Labels

Future implementation should add exactly these labels first:

| Profile label | Purpose | Default CI status |
| --- | --- | --- |
| `performance-smoke` | Fast scale check for regular development. | Optional PR job or local command. |
| `performance-scale` | Nightly scale coverage for common large-library paths. | Nightly or scheduled CI only. |
| `performance-stress` | Manual stress and release-candidate coverage. | Manual only. |

The labels are intentionally separate from `malformed-media`. A scenario may
combine labels only when both profile budgets can be honored. For example, a
future corrupted performance scenario must still fit the selected performance
budget and must keep corruption opt-in.

## Size Budgets

Budgets are hard ceilings for checked-in profile scenarios and generated run
artifacts. A scenario that exceeds any ceiling belongs in a larger profile or is
out of scope for V1.

| Budget | `performance-smoke` | `performance-scale` | `performance-stress` |
| --- | ---: | ---: | ---: |
| Media assets | 40 | 250 | 1,000 |
| Works | 40 | 250 | 1,000 |
| Variants | 60 | 400 | 1,800 |
| Bundles | 8 | 50 | 200 |
| Sidecars | 120 | 750 | 3,000 |
| Timeline events | 160 | 1,200 | 6,000 |
| Materialized bytes under `library/` | 250 MB | 2 GB | 10 GB |
| Wall-clock run duration | 5 minutes | 30 minutes | 2 hours |
| Minimum free disk before run | 1 GB | 8 GB | 40 GB |

Byte budgets use decimal units: 1 MB is 1,000,000 bytes and 1 GB is
1,000,000,000 bytes.

The smoke profile is the only profile allowed in regular development loops. It
is deliberately larger than the first pack but small enough to diagnose scanner,
watcher, and adapter regressions without producing multi-gigabyte artifacts.

## Fixture Budget Rules

Performance scenarios must remain source fixtures, not checked-in materialized
libraries. Generated outputs stay under the caller's run directory and are
deleted by the normal cleanup workflow.

Each future performance fixture must document its expected profile label and
budget class in the fixture review checklist or adjacent test metadata. The
implementation should validate the budget from generated artifacts rather than
trusting comments in YAML.

Scenarios should prefer many short deterministic assets over a few long assets.
Long clips are reserved for progress and wall-clock coverage, and they must not
be the default way to hit byte budgets.

## Capability Skip Rules

Performance profile tests may skip only when an explicit required capability is
missing or below the project minimum version. A skip must name the missing tool
or provider and the profile label it blocked.

Allowed skip reasons:

- `ffmpeg` missing or below the minimum required version.
- `ffprobe` missing or below the minimum required version.
- A future profile-specific provider is unavailable and reported by
  `chaos-librarian capabilities --json`.
- The CI tier has not opted into the requested profile label.

Disallowed skip reasons:

- The scenario is "too slow" without naming the profile budget it exceeds.
- The selected CI runner lacks the minimum free disk required by the profile.
- A broad catch-all integration-test skip that hides which capability failed.

When a capability is missing, the test outcome should be a visible pytest skip,
not a silent pass and not a downgraded profile.

Disk capacity is an infrastructure precondition, not a capability skip. CI jobs
that opt into a performance profile must provision at least the profile's
minimum free disk before the first run starts. If the runner cannot satisfy that
precondition, the job should fail during setup with an actionable message.

## CI Tiers

| Tier | Trigger | Allowed profiles | Required gates |
| --- | --- | --- | --- |
| Fast | Pull request and `main` push | No performance profiles by default. | Unit tests, docs tests, schema drift, lint, type check. |
| Extended | Scheduled nightly or explicit maintainer dispatch | `performance-smoke`, `performance-scale` | Fast gates plus materialize/run/compare recipes for selected profile fixtures. |
| Stress | Manual release-candidate dispatch | `performance-stress` | Extended gates plus long wall-clock and cleanup validation. |

Fast CI may add a `performance-smoke` job only if the job is independently
selectable and can be disabled without weakening the default gate. `scale` and
`stress` must never run on every pull request.

## Verification Expectations

The implementation that adds these profiles should include:

- Contract tests for each new profile label.
- Fixture tests that fail when a scenario exceeds its declared profile budget.
- Integration tests that exercise visible capability skips.
- Documentation tests that keep the CI-tier policy discoverable.
- A manual verification note with materialized byte counts and elapsed time for
  each new performance fixture.

## Out Of Scope

- Adding profile labels to the current Pydantic contract.
- Adding performance fixture YAML files.
- Adding CI workflow jobs.
- Implementing a profile generator.
- Changing default first-pack fixture budgets.
