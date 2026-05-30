# Issue #108 — Pre-Built Scenario Recipe Library

> Status: Draft · Sprint: issue-108 · Schema impact: none

## Problem

New users must author scenarios from scratch before chaos-librarian gives them
any value. The framework is expressive, but the blank-page cost is high: a team
has to learn the timeline event vocabulary, profile names, and path conventions
before running a single meaningful chaos test. A curated set of ready-to-run
scenarios that target known media-library failure patterns lowers that barrier
and makes the tool useful on first install.

## Goals

- Ship a curated `recipes/` directory of ready-to-run scenario YAML files,
  grouped by failure-pattern category, with at least three recipes per category.
- Every shipped recipe is a *genuinely valid* scenario: it passes
  `chaos-librarian validate` with `valid: true`.
- A CI test re-validates every recipe on every run so a future schema/validation
  change cannot let a recipe rot silently.
- Each recipe is self-documenting (header comment) and indexed in a README that
  states what it tests, the expected consumer response, and any required profile.
- Recipes are pinned to the current scenario schema version and the pin is
  enforced, so a schema bump forces a conscious recipe update.

## Non-goals

- Generating recipes programmatically (`generate` already exists; recipes are
  hand-curated, human-readable starting points).
- Encoding the *consumer's* expected policy outcome in machine-readable form.
  chaos-librarian is policy-neutral; expected-response text is documentation only.
- Shipping recipes for proposed failure patterns that the scenario schema cannot
  express (see "Dropped proposals").
- Wiring recipes into `materialize`/`run` CI. Validation is the CI contract; a
  recipe that materializes is out of scope for this issue.

## What the scenario schema can express (verified)

Source of truth: `src/chaos_librarian/contract/scenario.py`,
`contract/domain.py`, `contract/content_sources.py`, `contract/patterns.py`.

- Timeline actions (discriminator `action`, every event has `at: int ≥ 1`):
  `add_asset`, `add_sidecar`, `move_asset`, `delete_asset`, `replace_content`,
  `slow_copy_start`, `slow_copy_commit`, `promote_from_archive`,
  `demote_to_archive`.
- Root kinds: `movies`, `tv`, `music`, `archive`, `other`.
- Asset classes: `movie`, `episode`, `track`, `other`.
- Sidecar kinds: `subtitle`, `poster`, `nfo`, `artwork`, `other` (subtitle
  requires a BCP-47 `language`).
- Profiles: `default`, `malformed-media`, `duplicate-variants`, `performance`,
  `network-filesystem`.
- Content source: `kind` (`synthetic`/`pattern`), `codec`
  (`h264`/`h265`/`aac`/`flac`), `container` (`mp4`/`matroska`/`webm`/`ogg`),
  `duration_seconds`, `corruption: {mode: header|packets|truncate, at_byte?}`,
  `network_lag: {open_latency_ms?, read_throughput_kbps?}`,
  `duplicate_variant: {group, role: primary|duplicate}`.
- Validation rejects: schema-shape errors, path escapes
  (`E_PATH_ESCAPE`), live-path collisions (`E_PATH_DUPLICATE`), duplicate ids
  (`E_ID_DUPLICATE`), decreasing `at` (`E_TIMELINE_ORDER`), illegal lifecycles
  (`E_LIFECYCLE_INVALID`: add-on-placed, move-after-delete, double slow-copy),
  unpaired slow copy (`E_SLOW_COPY_INVALID`), missing/malformed subtitle language
  (`E_SIDECAR_LANGUAGE_INVALID`), and profile/content-source mismatches.

## Recipe set

Six categories, ≥3 recipes each. Every recipe below maps to real schema
capabilities and validates clean. "Expected consumer response" is descriptive
prose for the README/header, not a machine assertion.

### `recipes/scanner/` — scanner resilience
| Recipe | Mechanism | Tests |
| --- | --- | --- |
| `file-during-scan.yaml` | `add_asset` at a later step | A new file appears while a scan is in progress. |
| `deleted-midscan.yaml` | seed asset + `delete_asset` mid-timeline | A file vanishes while the scanner is iterating. |
| `moved-during-scan.yaml` | seed asset + `move_asset` mid-timeline | A file is relocated during a scan. |

### `recipes/watcher/` — watcher/daemon stress
| Recipe | Mechanism | Tests |
| --- | --- | --- |
| `rapid-churn.yaml` | `add`→`move`→`delete` across two roots | Rapid create/rename/delete churn. |
| `slow-copy-race.yaml` | `slow_copy_start` + concurrent `add_asset` + `slow_copy_commit` | A slow copy in flight while other events fire. |
| `nfs-stale-handle.yaml` | `network-filesystem` profile + `slow_copy` with `network_lag` | High-latency ingest that mimics a flaky network mount. |
| `rename-during-move.yaml` | two chained `move_asset` events | A rename that fires between move events. |

### `recipes/identity/` — identity and dedup
| Recipe | Mechanism | Tests |
| --- | --- | --- |
| `same-content-different-path.yaml` | `duplicate-variants` profile, primary + duplicate variant | Identical asset at two paths. |
| `same-path-different-content.yaml` | `replace_content` | Same path, content replaced. |
| `cross-root-duplicate.yaml` | duplicate variant added in a second root | The same content surfaces under two roots. |

### `recipes/metadata/` — metadata corruption
| Recipe | Mechanism | Tests |
| --- | --- | --- |
| `corrupt-header.yaml` | `malformed-media` + `corruption.mode: header` | Container header corruption. |
| `corrupt-packets.yaml` | `malformed-media` + `corruption.mode: packets` | Mid-stream packet corruption. |
| `truncated-file.yaml` | `malformed-media` + `corruption.mode: truncate` | A file cut short mid-stream. |

### `recipes/sidecar/` — sidecar chaos
| Recipe | Mechanism | Tests |
| --- | --- | --- |
| `subtitle-language-swap.yaml` | seed subtitle + `add_sidecar` in another language | A second-language subtitle appears. |
| `late-subtitle.yaml` | episode with no subtitle, `add_sidecar` subtitle later | A subtitle that materializes after the asset. |
| `nfo-poster-pair.yaml` | seed `nfo` + `poster`, `add_sidecar` `artwork` later | Companion metadata/artwork sidecars. |

### `recipes/archive/` — archive and discovery
| Recipe | Mechanism | Tests |
| --- | --- | --- |
| `to-archive.yaml` | `demote_to_archive` | An active asset is archived. |
| `from-archive.yaml` | `promote_from_archive` | An archived asset is restored. |
| `round-trip.yaml` | `demote_to_archive` then `promote_from_archive` | Archive then restore of one asset. |

## Dropped proposals

These appeared in the issue but cannot be shipped as valid scenarios; shipping a
"recipe" that does not validate, or that fakes a capability, would violate the
project's no-phantom-features rule. Each is recorded here and (per AGENTS.md
Rule 13) filed as a follow-up issue if it warrants future schema work.

| Proposed | Why dropped |
| --- | --- |
| `scanner/symlink-external` | A path outside the library root is rejected by `E_PATH_ESCAPE`; a valid recipe cannot express it. |
| `scanner/hardlink-duplicates` | No inode/hardlink concept in the schema. |
| `scanner/empty-directory` | Assets are files; the schema has no directory-only entity. |
| `identity/hash-collision-simulation` | No knob to control or truncate content hashes. |
| `metadata/wrong-oracle-hash` | The oracle manifest is generated, not authored; an author cannot inject a wrong hash. |
| `metadata/invalid-duration` | `duration_seconds` is a plain positive integer; "wrong" is a consumer judgment, not an authoring knob. |
| `sidecar/wrong-encoding` | Sidecars carry no byte-encoding knob. |
| `sidecar/nfo-xml-injection` | Sidecars carry no content/body knob. |
| `sidecar/poster-is-video` | Sidecars carry no media-type knob; nothing distinguishes the bytes. |

## Design

Location and bit-rot-guard decisions are recorded in
[ADR 0002](../../adr/0002-recipe-library-location-and-bitrot-guard.md).

### Location and layout
`recipes/` at the repo root, one subdirectory per category, one YAML file per
recipe (`recipes/<category>/<name>.yaml`). A top-level `recipes/README.md`
indexes every recipe.

### Recipe file shape
Each recipe is a normal scenario document plus a header comment block. The header
is a YAML comment (lines beginning `#`) so it does not affect parsing:

```yaml
# Recipe: <human title>
# Category: <category>
# Tests: <one line — the failure pattern exercised>
# Expected consumer response: <converges | errors | diverges> — <why>
# Requires: <profile name or "none"; any CLI flags>
schema_version: 1
seed: <int>
...
```

The header's first line is `# Recipe:` — deliberately **not** `# expected:`,
which is reserved for the invalid-fixture corpus. Recipes also set the existing
`timeline_note` field where a short in-document note aids reading.

### Schema-version pinning
Every recipe sets `schema_version: 1` (the current `SCENARIO_SCHEMA_VERSION`).
The corpus test asserts each recipe's `schema_version` equals the current
constant, so a schema bump that does not update the recipes fails CI — making
"updated when schema changes" an enforced contract rather than a hope.

### CI corpus test
A new test `tests/recipes/test_recipe_corpus.py`:
- Discovers recipes with `rglob("*.yaml")` rooted at the repo-root `recipes/`
  (recursive, because recipes are nested by category — the existing
  `test_sample_scenarios.py` uses non-recursive `glob` and would miss them).
- Fails loudly if discovery finds **zero** recipes (guards against a silent
  pass when the directory is empty or the path resolves wrong).
- For each recipe: loads it through `Scenario.model_validate`, asserts
  `schema_version == SCENARIO_SCHEMA_VERSION`, and asserts
  `validate_scenario_file(path).valid` is `True`, surfacing the findings on
  failure.
- Asserts every expected category subdirectory exists and holds ≥3 recipes, so
  the acceptance-criteria floor is itself tested.

The test calls the validation pipeline directly (the handler/function is the unit
of test), not the CLI subprocess.

### README
`recipes/README.md`: a short intro plus one table per category (recipe path,
what it tests, expected consumer response, required profile). It also states the
schema-version pin and points at the corpus test as the bit-rot guard.

## Failure modes and edge cases

- **Empty/zero discovery** → corpus test fails (explicit assertion), not a silent
  pass.
- **A recipe stops validating after a schema change** → corpus test fails with the
  offending file and its findings.
- **Schema version bumped without updating recipes** → version-pin assertion
  fails, naming the recipe.
- **A category drops below three recipes** → count assertion fails.
- **Accidental `# expected:` header on a recipe** → harmless; recipes are not in
  the invalid corpus, so `test_invalid_corpus.py` never reads them. The recipe
  header standard avoids that prefix regardless.

## Acceptance criteria

- [ ] `recipes/` exists with ≥3 recipes in each of the six categories.
- [ ] Every recipe passes `chaos-librarian validate` (asserted by the corpus
      test in CI via `validate_scenario_file`).
- [ ] `recipes/README.md` documents each recipe with description and expected
      consumer response.
- [ ] Recipes are version-pinned and the pin is CI-enforced against
      `SCENARIO_SCHEMA_VERSION`.

## Testing

- `tests/recipes/test_recipe_corpus.py` as described above: per-recipe parse +
  validate-clean + version-pin, plus directory-structure/count assertions and a
  non-empty-discovery guard.
- Tests verify intent (every shipped recipe is runnable and stays runnable), not
  just mechanics, per AGENTS.md Rule 9.
