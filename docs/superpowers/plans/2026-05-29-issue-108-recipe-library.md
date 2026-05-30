# Plan — Issue #108 Pre-Built Scenario Recipe Library

Spec: [`2026-05-29-issue-108-recipe-library-design.md`](../specs/2026-05-29-issue-108-recipe-library-design.md)
· ADR: [`0002`](../../adr/0002-recipe-library-location-and-bitrot-guard.md)

No source/model/schema changes — recipes are pure YAML plus one new test and a
README. The CI guardrails (ruff, ty, pytest, schema drift) must stay green at
every commit.

## Phase 0 — Pre-reqs (done)
- Branch `feat/scenario-recipe-library-108` off latest `main`. ✓
- Spec + ADR committed and adversarially reviewed. ✓
- Verified templates exist for every action used (see spec "Ground truth" table).

## Phase 1 — Failing corpus test (TDD red)
Write `tests/recipes/test_recipe_corpus.py` before any recipe exists:
- `RECIPES_DIR = Path(__file__).resolve().parents[2] / "recipes"`.
- `test_recipes_directory_is_populated`: `rglob("*.yaml")` non-empty (fails now).
- `test_category_has_minimum_recipes[category]`: each of the six category dirs
  holds ≥3 `*.yaml`.
- `test_recipe_validates_clean[path]`: `run_validation(prepare_run_input(path))`
  → `report.ok is True and report.issues == []`, parametrized over every recipe,
  ids = path relative to `recipes/`.

Run `uv run python -m pytest tests/recipes -q` → confirm the populated/count
tests FAIL (red). This proves the guard fires before recipes exist.

## Phase 2 — Author recipes (TDD green), per category
Each recipe: header comment block (`# Recipe:` … `# Requires:`),
`schema_version: 23`, structural body copied from the named template fixture.
After each category, run the corpus test for those files and fix any issue codes
before moving on. Recipes (21 total):

- `scanner/`: `deleted-midscan` (`delete_file`), `moved-during-scan`
  (`move_asset`), `renamed-during-scan` (`rename_file`), `delete-then-restore`
  (`delete_file`+`add_file`).
- `watcher/`: `slow-copy-race` (`slow_copy_start`/`commit`; commit.at =
  start.at+duration), `nfs-lag-visibility` (`network-fs-lag`;
  `network_lag_start` delayed_visibility + `commit`), `rapid-churn`
  (`delete_file`+`add_file`+`move_asset`), `mtime-touch` (`filesystem-artifacts`;
  `touch_mtime` offset).
- `identity/`: `move-and-rename` (`move_asset`+`rename_file`), `cross-root-move`
  (`move_between_roots`), `remux-container` (`remux_container` mkv→mp4).
- `metadata/`: `corrupt-container-header` (`malformed-media`), `truncated-file`
  (`malformed-media`; `truncate_file` keep_bytes), `corrupt-packet-range`
  (`malformed-media`; `corrupt_packet_range`), `wrong-oracle-hash`
  (`negative-oracle`; `wrong_oracle_hash`).
- `sidecar/`: `late-subtitle` (`create_sidecar` subtitle+language),
  `poster-and-nfo` (`create_sidecar` poster + nfo, no language),
  `second-language-subtitle` (declared `eng` subtitle + `create_sidecar` `fra`).
- `archive/`: `archive-on-event` (sentinel `archive_root`), `archive-explicit-root`
  (named archive root), `relocate-then-archive` (`move_between_roots`+`archive_file`).

Run the full `tests/recipes` suite → all green.

## Phase 3 — README
`recipes/README.md`: intro + one table per category (path, what it tests,
expected consumer response, required profile) + the schema-version-pin note and a
pointer to the corpus test as the bit-rot guard.

## Phase 4 — Guardrails
`uv run ruff check`, `uv run ruff format`, `uv run ty check src tests`,
`uv run python -m pytest -q` (full suite, to confirm no collection/path
regressions), `uv run python -m chaos_librarian.schema_export --check` (must be a
no-op — no model change). Fix every warning.

## Phase 5 — Gap issues (AGENTS Rule 13)
File GitHub issues for the dropped capabilities so the gaps are tracked:
hardlink/inode modeling, symlink-policy scenarios, content-hash dedup authoring,
and sidecar encoding/body knobs. Each: one-line title, 2-3 sentences, pointer to
this spec's "Dropped proposals", surfaced-by `#108`.

## Phase 6 — Adversarial review of the diff (step 6)
`/challenge main..HEAD`; address defensible findings via
`superpowers:receiving-code-review`; commit per logical change; loop to approve
or 5 iterations.

## Phase 7 — Ship
Push; open PR vs `main` ending `Closes #108`; watch `gh pr checks --watch` until
required checks pass (gdbstub/libvirt/drgn skips expected); hand off.

## Rollback / cleanup
Pure additive change (new `recipes/`, one new test, one README, docs). Revert =
delete `recipes/` and `tests/recipes/` and the doc commits; nothing else
references them. No data migration, no external state.

## Verification gates (each must pass before advancing)
1. Phase 1: corpus test fails red (proves the guard works).
2. Phase 2: every recipe validates clean; category counts ≥3.
3. Phase 4: ruff/ty/pytest/schema-drift all green.
4. Phase 6: challenge returns approve (or 5 iterations).
