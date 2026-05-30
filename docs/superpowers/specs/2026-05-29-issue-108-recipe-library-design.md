# Issue #108 — Pre-Built Scenario Recipe Library

> Status: Draft · Sprint: issue-108 · Schema impact: none

## Problem

New users must author scenarios from scratch before chaos-librarian gives them
any value. The framework is expressive, but the blank-page cost is high: a team
has to learn the timeline action vocabulary, profile opt-ins, the media
hierarchy, and path conventions before running a single meaningful chaos test. A
curated set of ready-to-run scenarios that target known media-library failure
patterns lowers that barrier and makes the tool useful on first install.

## Goals

- Ship a curated `recipes/` directory of ready-to-run scenario YAML files,
  grouped by failure-pattern category, with at least three recipes per category.
- Every shipped recipe is a *genuinely valid* scenario: `chaos-librarian
  validate` exits 0 (`report.ok is True`, no issues).
- A CI test re-validates every recipe on every run so a future schema or
  validation change cannot let a recipe rot silently.
- Each recipe is self-documenting (header comment) and indexed in a README that
  states what it tests, the expected consumer response, and any required profile.
- Recipes are pinned to the current scenario schema version and that pin is
  CI-enforced.

## Non-goals

- Generating recipes programmatically (`generate` already exists; recipes are
  hand-curated, human-readable starting points).
- Encoding the *consumer's* expected policy outcome in machine-readable form.
  chaos-librarian is policy-neutral; expected-response text is documentation only.
- Shipping recipes for proposed failure patterns the scenario schema cannot
  express (see "Dropped proposals").
- Wiring recipes into `materialize`/`run` CI. Validation is the CI contract; a
  recipe that materializes is out of scope for this issue.

## Ground truth: what the scenario schema actually is

Verified against `src/chaos_librarian/contract/scenario.py`,
`contract/profiles.py`, `contract/__init__.py`, and the
`tests/fixtures/scenarios/*.yaml` corpus (each fixture's first line is
`# expected: clean`).

Top-level `Scenario` (required keys): `schema_version` (`Literal[23]` —
`SCENARIO_SCHEMA_VERSION = 23`), `scenario_id`, `seed` (int ≥ 0 or `"random"`),
`duration_scale` (`short|normal|long`), `library`, `movies`, `series`,
`artists`, `timeline`. Optional: `profiles` (list), `generation`.

- `library.roots[*]` is `{id, path}` (no "kind"). Optional `library.archive_root`
  (a root id, or the sentinel `archive`).
- Assets are **nested**, not flat: `movies|series|artists → variants → bundle →
  assets`. An asset is `{id, role, container, duration_seconds, video?, audio?,
  subtitles?}`.
- `timeline[*]` is a discriminated union on `action` with **30** variants. Every
  event has `id` and `at` (a duration **string**, e.g. `"1s"`).
- Sidecar kinds: `subtitle` (requires `language`), `poster`, `nfo` (forbid
  `language`).
- Profiles: `malformed-media`, `performance-smoke|scale|stress`,
  `network-fs-lag`, `filesystem-artifacts`, `negative-oracle`,
  `fuzz-smoke|regression`.

### Timeline actions used by these recipes (with required fields)

| action | fields | profile required |
| --- | --- | --- |
| `delete_file` | `target` | — |
| `add_file` | `target`, `to` | — |
| `move_asset` | `target`, `to` | — |
| `rename_file` | `target`, `to` | — |
| `move_between_roots` | `target`, `from_root_id`, `to_root_id` | — |
| `archive_file` | `target` (needs `library.archive_root`) | — |
| `create_sidecar` | `target`, `to`, `kind` (subtitle adds `language`) | — |
| `slow_copy_start` / `slow_copy_commit` | `target`,`to`,`temp_path`,`duration` / `for` | — |
| `remux_container` | `target`, `to_container` | — |
| `reencode_video` | `target`, `resolution`, `codec` | — |
| `corrupt_container_header` | `target`, `bytes?` | `malformed-media` |
| `truncate_file` | `target`, `keep_bytes` | `malformed-media` |
| `corrupt_packet_range` | `target`, `packet_start`, `stream?`, `packet_count?` | `malformed-media` |
| `wrong_oracle_hash` | `target` | `negative-oracle` |
| `network_lag_start` / `network_lag_commit` | `effect`,`target`,`after`,`duration` / `for` | `network-fs-lag` |
| `touch_mtime` | `target`, `offset` | `filesystem-artifacts` |

The profile column is enforced: omitting it yields `E_PROFILE_REQUIRED` (see the
`*-missing-profile.yaml` invalid fixtures). `slow_copy_commit.at` must equal
`start.at + start.duration` (`E_SLOW_COPY_TIMING`); `temp_path` must differ from
both the final and current path (`E_SLOW_COPY_PATH_COLLISION`).

## Recipe set

Six categories, ≥3 recipes each. Every recipe maps to real actions and validates
clean. "Expected consumer response" is descriptive prose for the README/header,
not a machine assertion. Each recipe's structural template is an existing valid
fixture (named in the last column) so authoring is copy-and-adapt, not invention.

### `recipes/scanner/` — scanner resilience
| Recipe | Action(s) | Tests | Template |
| --- | --- | --- | --- |
| `deleted-midscan.yaml` | `delete_file` | A tracked file disappears mid-scan. | `delete-add-restore.yaml` |
| `moved-during-scan.yaml` | `move_asset` | A file is relocated during a scan. | `identity-move-rename.yaml` |
| `renamed-during-scan.yaml` | `rename_file` | A file is renamed in place during a scan. | `identity-move-rename.yaml` |
| `delete-then-restore.yaml` | `delete_file` + `add_file` | A file vanishes then reappears at a new path. | `delete-add-restore.yaml` |

### `recipes/watcher/` — watcher/daemon stress
| Recipe | Action(s) | Tests | Template |
| --- | --- | --- | --- |
| `slow-copy-race.yaml` | `slow_copy_start` + `slow_copy_commit` | An incomplete file becomes visible only on commit. | `slow-copy.yaml` |
| `nfs-lag-visibility.yaml` | `network_lag_start/commit` (`network-fs-lag`) | Delayed visibility from a laggy network mount. | invalid `*-missing-profile` + scenario-authoring §Profiles |
| `rapid-churn.yaml` | `delete_file`+`add_file`+`move_asset` | Rapid create/relocate/delete churn. | `active-library-churn.yaml` |
| `mtime-touch.yaml` | `touch_mtime` (`filesystem-artifacts`) | A bare mtime change with no content change. | scenario-authoring §Profiles |

### `recipes/identity/` — durable identity through mutation
chaos-librarian has no content-hash dedup knob, so "dedup" is expressed as
*identity survival across mutations*, not collision authoring.
| Recipe | Action(s) | Tests | Template |
| --- | --- | --- | --- |
| `move-and-rename.yaml` | `move_asset` + `rename_file` | Identity must survive a move then a rename. | `identity-move-rename.yaml` |
| `cross-root-move.yaml` | `move_between_roots` | Identity must survive moving between roots. | `move-between-roots.yaml` |
| `remux-container.yaml` | `remux_container` | Identity must survive a container swap (mkv→mp4). | `remux-container.yaml` |

### `recipes/metadata/` — metadata corruption (`malformed-media` / `negative-oracle`)
| Recipe | Action(s) | Tests | Template |
| --- | --- | --- | --- |
| `corrupt-container-header.yaml` | `corrupt_container_header` | Container header corruption. | `malformed-container-header.yaml` |
| `truncated-file.yaml` | `truncate_file` | A file cut short mid-stream. | invalid `truncate-file-missing-profile` (add profile) |
| `corrupt-packet-range.yaml` | `corrupt_packet_range` | Mid-stream packet corruption. | `malformed-container-header.yaml` (swap action) |
| `wrong-oracle-hash.yaml` | `wrong_oracle_hash` (`negative-oracle`) | Oracle records a deliberately wrong content hash. | `negative-oracle-hash.yaml` |

### `recipes/sidecar/` — sidecar chaos
| Recipe | Action(s) | Tests | Template |
| --- | --- | --- | --- |
| `late-subtitle.yaml` | `create_sidecar` (subtitle, language) | A subtitle that materializes after the asset. | `sidecar-create-via-timeline.yaml` |
| `poster-and-nfo.yaml` | `create_sidecar` kind `poster` + kind `nfo` | Non-subtitle companion sidecars (no language). | `sidecar-create-via-timeline.yaml` + `SidecarKind` |
| `second-language-subtitle.yaml` | declared `eng` subtitle + `create_sidecar` `fra` | A second-language subtitle appears. | `subtitle-ops-on-mp4.yaml` |

Distinct `(target, language)` per `create_sidecar` avoids
`E_SIDECAR_LANGUAGE_INVALID`.

### `recipes/archive/` — archive and discovery
| Recipe | Action(s) | Tests | Template |
| --- | --- | --- | --- |
| `archive-on-event.yaml` | `archive_file` (sentinel `archive_root`) | An active asset is archived. | `archive-file.yaml` |
| `archive-explicit-root.yaml` | `archive_file` (explicit `archive_root` id) | Archiving into a named archive root. | `archive-file-explicit-root.yaml` |
| `relocate-then-archive.yaml` | `move_between_roots` + `archive_file` | An asset relocated across roots, then archived. | `move-between-roots.yaml` + `archive-file.yaml` |

## Dropped proposals

These appeared in the issue but cannot ship as valid scenarios; a "recipe" that
does not validate, or fakes a capability, would violate the no-phantom-features
rule. Each is recorded and (per AGENTS.md Rule 13) filed as a follow-up issue if
it warrants future schema work.

| Proposed | Why dropped |
| --- | --- |
| `scanner/symlink-external` | Paths outside a library root are rejected by `E_PATH_CONTAINMENT`. |
| `scanner/hardlink-duplicates` | No inode/hardlink concept in the schema. |
| `scanner/empty-directory` | Assets are files; there is no directory-only entity. |
| `identity/hash-collision-simulation` | No knob to control or truncate content hashes. |
| `sidecar/wrong-encoding` | Sidecar subtitles expose `encoding`, but the only invalid-fixture evidence (`subtitle-ass-utf16`) shows encoding combos are constrained; deferring rather than risk an invalid recipe. |
| `sidecar/nfo-xml-injection` | NFO sidecars carry no authorable body. |
| `sidecar/poster-is-video` | No media-type check distinguishes a poster's bytes; would be misleading. |

Note: `metadata/wrong-oracle-hash` and packet-range corruption, dropped in the
first draft, are in fact expressible (`wrong_oracle_hash`,
`corrupt_packet_range`) and are now shipped.

## Design

Location and bit-rot-guard decisions are recorded in
[ADR 0002](../../adr/0002-recipe-library-location-and-bitrot-guard.md).

### Location and layout
`recipes/` at the repo root, one subdirectory per category, one YAML file per
recipe (`recipes/<category>/<name>.yaml`). A top-level `recipes/README.md`
indexes every recipe.

### Recipe file shape
Each recipe is a normal scenario document plus a header comment block (YAML
comment lines, so parsing is unaffected):

```yaml
# Recipe: <human title>
# Category: <category>
# Tests: <one line — the failure pattern exercised>
# Expected consumer response: <converges | errors | diverges> — <why>
# Requires: <profile name(s) or "none">
schema_version: 23
scenario_id: <id>
...
```

The header's first line is `# Recipe:` — deliberately not `# expected:`, the
prefix the fixture corpus uses (`# expected: clean` / `# expected: E_<CODE>`).

### Schema-version pinning (currency is automatic)
Every recipe sets `schema_version: 23`. Because the model declares
`schema_version: Literal[23]`, the validate-clean corpus test **already**
enforces currency: when `SCENARIO_SCHEMA_VERSION` is next bumped, every recipe's
literal stops matching, validation fails, and the corpus test goes red — forcing
a deliberate recipe update. No separate `== SCENARIO_SCHEMA_VERSION` assertion is
needed (it would only add a second, redundant failure mode and per-file churn).
This mirrors how the existing fixture corpus is bumped en masse each version.

### CI corpus test
A new test `tests/recipes/test_recipe_corpus.py`:
- Resolves the repo-root recipes dir as `Path(__file__).resolve().parents[2] /
  "recipes"` (file at `tests/recipes/test_recipe_corpus.py` → `parents[2]` is the
  repo root) and discovers recipes with `rglob("*.yaml")` (recursive, because
  recipes nest by category; the existing `test_sample_scenarios.py` uses
  non-recursive `glob` and would miss them).
- Fails loudly if discovery finds **zero** recipes (guards against a silent pass
  when the directory is empty or the path resolves wrong).
- Asserts each expected category subdirectory exists and holds ≥3 recipes, so the
  acceptance-criteria floor is itself tested.
- For each recipe, runs the real validation entrypoint —
  `run_validation(prepare_run_input(path))` from `chaos_librarian.validation` —
  and asserts `report.ok is True` and `report.issues == []`, surfacing
  `[i.code for i in report.issues]` on failure. This is exactly what
  `chaos-librarian validate` runs (`cli/commands/validate.py`) and mirrors
  `tests/validation/test_invalid_corpus.py::test_valid_fixture_validates_clean`.

The test calls the validation function directly, not the CLI subprocess.

### README
`recipes/README.md`: a short intro plus one table per category (recipe path,
what it tests, expected consumer response, required profile). It states the
schema-version pin and points at the corpus test as the bit-rot guard.

## Failure modes and edge cases

- **Empty/zero discovery** → corpus test fails (explicit assertion), not a silent
  pass.
- **A recipe stops validating after a schema/validation change** → corpus test
  fails with the offending file and its issue codes.
- **Schema version bumped** → every recipe's `Literal[23]` mismatch fails the
  corpus test, naming the files to update (the intended forcing function).
- **A category drops below three recipes** → count assertion fails.
- **Profile-gated action without its profile** → that recipe fails the corpus
  test with `E_PROFILE_REQUIRED`; the header's `Requires:` line and the action
  table above are the authoring guard.
- **`slow_copy` timing/path mistakes** → `E_SLOW_COPY_TIMING` /
  `E_SLOW_COPY_PATH_COLLISION` caught by the corpus test.

## Acceptance criteria

- [ ] `recipes/` exists with ≥3 recipes in each of the six categories.
- [ ] Every recipe passes `chaos-librarian validate` (asserted by the corpus test
      via `prepare_run_input` + `run_validation`, `report.ok is True`).
- [ ] `recipes/README.md` documents each recipe with description and expected
      consumer response.
- [ ] Recipes are version-pinned (`schema_version: 23`) and currency is
      CI-enforced by the validate-clean guard.

## Testing

- `tests/recipes/test_recipe_corpus.py` as described: per-recipe validate-clean,
  plus directory-structure/count assertions and a non-empty-discovery guard.
- Tests verify intent (every shipped recipe is runnable and stays runnable) per
  AGENTS.md Rule 9, and use the same public validation API as the shipped CLI.
