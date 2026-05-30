# Movie Release/Edition Modeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let scenarios author a movie *edition* (theatrical / director's cut / extended / unrated) as an optional attribute on `Variant`, rendered as a Plex/Jellyfin `{edition-<Name>}` filename-stem token, without a new hierarchy layer, new `ParentKind`, movie-shape migration, or manifest bump.

**Architecture (Option A):** `Variant.edition: EditionKind | None = None`. The token renders into the movie filename stem only. The edition reaches the rendered path through the scenario `Variant` at **initial seeding** (`topology.renderable_asset_context`, which reads the scenario object directly). No movie hierarchy/path action exists (and `relabel_edition` is deferred), so the manifest-based re-render path (`WorldState.renderable_context_for_asset`) is never reached for a movie asset — that is why the manifest needs no `edition` field and `MANIFEST_SCHEMA_VERSION` stays 10. Scenario schema v30 → 31; manifest unchanged at v10.

**Tech Stack:** Python 3.13, Pydantic v2, `uv`, `ruff`, `ty`, `pytest`. Schema source-of-truth is the Pydantic models; `schema_export --write` regenerates `schemas/*.json`.

**Reference docs:** spec `docs/superpowers/specs/2026-05-30-issue-117-movie-edition-design.md`; ADR `docs/adr/0010-movie-edition-modeling.md`; conventions in `AGENTS.md` ("Project-specific conventions").

**Guardrail gate (run before EVERY commit, must be clean):**
```bash
uv run ruff check . && uv run ruff format --check . \
  && uv run ty check src tests \
  && uv run python -m chaos_librarian.schema_export --check \
  && uv run python -m pytest -q --no-cov tests/contract tests/validation
```
(Full `uv run python -m pytest -q --no-cov` once at the end.)

**Convention reminders (from AGENTS.md — violating these fails CI):**
- Enums: `class X(enum.StrEnum):`.
- Every BaseModel: `model_config = ConfigDict(extra="forbid")` (hierarchy models also `frozen=True`). `Variant` is already frozen — do not change that.
- `schema_version` is hardcoded `Literal[N]`, never `Literal[CONST]`.
- Negative tests: build a `dict` and call `Model.model_validate(payload)`; never construct invalid models with `# type: ignore`.
- Absolute imports only.
- After editing any `contract/` model: `schema_export --write` and commit the artifact in the same change.
- Worktree: all work on `feat/movie-edition-hierarchy-117`. Commit trailer `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Task 1: Scenario contract — EditionKind enum + Variant.edition + version bump + fixture re-pin

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (`EditionKind` enum, `Variant.edition`, `Scenario.schema_version` literal 30 → 31)
- Modify: `src/chaos_librarian/contract/__init__.py:16` (`SCENARIO_SCHEMA_VERSION` 30 → 31)
- Modify: `schemas/scenario.schema.json` (regen)
- Modify: every `tests/fixtures` + `recipes` scenario pinned at `schema_version: 30` (re-pin to 31)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing tests for the new field**

Add to `tests/contract/test_scenario.py` (build payloads as dicts and `model_validate`, per convention). Reuse the movie-variant payload shape already in that file (copy from an existing movie test):

```python
def test_variant_accepts_edition():
    from chaos_librarian.contract.scenario import EditionKind, Variant
    v = Variant.model_validate(_movie_variant_payload(edition="directors_cut"))
    assert v.edition is EditionKind.DIRECTORS_CUT


def test_variant_edition_defaults_none():
    from chaos_librarian.contract.scenario import Variant
    v = Variant.model_validate(_movie_variant_payload())
    assert v.edition is None


def test_variant_rejects_unknown_edition():
    import pytest
    from pydantic import ValidationError
    from chaos_librarian.contract.scenario import Variant
    with pytest.raises(ValidationError):
        Variant.model_validate(_movie_variant_payload(edition="unrated_extended_bogus"))
```

If no `_movie_variant_payload(edition=None)` helper exists, add one near the top of the file building the minimal `{id, label, bundle:{...}}` dict, inserting `"edition": edition` only when non-None.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_scenario.py -k edition -q --no-cov`
Expected: FAIL (`EditionKind` not importable / `edition` is `extra="forbid"`).

- [ ] **Step 3: Add `EditionKind` and `Variant.edition`**

In `src/chaos_librarian/contract/scenario.py`, immediately before the `Variant` class (it is defined ~line 542):

```python
class EditionKind(enum.StrEnum):
    """Movie release/edition cut (Plex/Jellyfin {edition-...} token)."""

    THEATRICAL = "theatrical"
    DIRECTORS_CUT = "directors_cut"
    EXTENDED = "extended"
    UNRATED = "unrated"
```

Add the field to `Variant` (keep it frozen, `extra="forbid"`):

```python
class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    label: str
    edition: EditionKind | None = None
    bundle: Bundle
```

- [ ] **Step 4: Bump the scenario version literal + constant**

In `Scenario`: change `schema_version: Literal[30]` → `Literal[31]`.
In `src/chaos_librarian/contract/__init__.py:16`: `SCENARIO_SCHEMA_VERSION: Final = 31`.

- [ ] **Step 5: Re-pin scenario fixtures and recipes (30 → 31) in the SAME commit**

The bump invalidates every scenario fixture/recipe pinned at 30, including the corpus `tests/contract/test_sample_scenarios.py` loads. Re-pin in the same change (macOS `sed -i ''`):

```bash
grep -rl "schema_version: 30" tests/fixtures recipes \
  | xargs sed -i '' 's/schema_version: 30/schema_version: 31/'
```

(New edition fixtures land in Task 4; only the re-pin happens here. The manifest constant `MANIFEST_SCHEMA_VERSION` stays 10 — do NOT touch it, and do NOT touch any `schema_version: 10` manifest test data.)

- [ ] **Step 6: Regenerate the scenario schema artifact**

Run: `uv run python -m chaos_librarian.schema_export --write`
Confirm with `git status --short schemas/`: **only** `scenario.schema.json` changes (the `Variant` `$defs` gains an optional `edition` enum). If `manifest.schema.json` or any report schema changes, STOP — that means something coupled the edition into the manifest, contradicting the design; investigate before continuing.

- [ ] **Step 7: Run the guardrail gate**

Run the full guardrail gate from the header.
Expected: PASS — fixtures re-pinned, scenario schema regenerated, manifest untouched.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract/scenario.py src/chaos_librarian/contract/__init__.py \
        tests/contract/test_scenario.py schemas/scenario.schema.json tests/fixtures recipes
git commit -m "feat: add Variant.edition and EditionKind (scenario v31)"
```

---

## Task 2: Path rendering — edition token in the movie filename stem

**Files:**
- Modify: `src/chaos_librarian/path_rendering.py`
- Test: `tests/contract/test_hierarchy_path_rendering.py`

- [ ] **Step 1: Write failing render tests**

Add to `tests/contract/test_hierarchy_path_rendering.py` (match the existing movie-render test construction in that module):

```python
def test_render_movie_flat_with_edition():
    from chaos_librarian.contract.domain import ParentKind
    from chaos_librarian.contract.scenario import EditionKind, MovieLayout
    from chaos_librarian.path_rendering import RenderableAssetContext, render_asset_path
    ctx = RenderableAssetContext(
        parent_kind=ParentKind.MOVIE,
        root_path="library/movies",
        layout=MovieLayout.MOVIE_FLAT,
        movie_title="Orbit",
        edition=EditionKind.DIRECTORS_CUT,
        variant_label="1080p",
        asset_role="primary_video",
        asset_container="mkv",
        bundle_asset_count=1,
    )
    assert render_asset_path(ctx) == (
        "library/movies/Orbit - 1080p {edition-Director's Cut}.mkv"
    )


def test_render_movie_edition_none_unchanged():
    # same ctx without edition renders the pre-change path (no token)
    ...
    assert render_asset_path(ctx) == "library/movies/Orbit - 1080p.mkv"


def test_render_movie_edition_after_role_suffix_multi_asset():
    # bundle_asset_count=2 -> "Orbit - 1080p - primary_video {edition-Extended}.mkv"
    ...


def test_each_edition_kind_renders_title_case_token():
    # theatrical->Theatrical, directors_cut->Director's Cut, extended->Extended, unrated->Unrated
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_hierarchy_path_rendering.py -k edition -q --no-cov`
Expected: FAIL (`RenderableAssetContext` has no `edition`).

- [ ] **Step 3: Add the `edition` field + display-name table**

In `src/chaos_librarian/path_rendering.py`:
- import `EditionKind` from `chaos_librarian.contract.scenario`.
- Add to `RenderableAssetContext` (a kw_only default field, before the required tail like the other optional domain fields):

```python
    edition: EditionKind | None = None
```

- Add an explicit display-name table near the top (not derived by string munging — `directors_cut` must render the apostrophe):

```python
_EDITION_DISPLAY_NAME: Final[dict[EditionKind, str]] = {
    EditionKind.THEATRICAL: "Theatrical",
    EditionKind.DIRECTORS_CUT: "Director's Cut",
    EditionKind.EXTENDED: "Extended",
    EditionKind.UNRATED: "Unrated",
}
```

(`Final` is already importable in this module? It is not today — add `from typing import Final`.) A new enum member with no table entry must fail loudly; see Step 4.

- [ ] **Step 4: Render the token in `_filename`**

`_filename` (path_rendering.py:129) builds `f"{stem} - {label}{role_suffix}.{container}"`. The edition token is appended to the **stem portion** (after label+role suffix, before the extension). Edit `_filename` so that, when `ctx.edition is not None`, it inserts the cleaned token before the `.`:

```python
def _filename(stem: str, ctx: RenderableAssetContext) -> str:
    label = clean_display_component(ctx.variant_label)
    role_suffix = ""
    if ctx.bundle_asset_count > 1:
        role_suffix = f" - {clean_display_component(ctx.asset_role)}"
    container = clean_asset_container(ctx.asset_container)
    edition_suffix = _edition_suffix(ctx.edition)
    return f"{stem} - {label}{role_suffix}{edition_suffix}.{container}"


def _edition_suffix(edition: EditionKind | None) -> str:
    if edition is None:
        return ""
    display = _EDITION_DISPLAY_NAME.get(edition)
    if display is None:
        raise ValueError(f"no display name for edition {edition!r}")
    return f" {{edition-{clean_display_component(display)}}}"
```

Note: `_filename` is shared by movie/episode/track/podcast stems. The spec scopes the token to movie variants only, but `edition` defaults to `None` for all non-movie contexts (the topology/state movie branch is the only one that sets it — Task 3), so non-movie stems are unaffected at runtime. Rendering the token in the shared `_filename` (rather than only the movie branch) keeps one code path and is correct because only movie contexts ever carry a non-None edition. Add a one-line comment stating this invariant.

- [ ] **Step 5: Run to verify pass + full module**

Run: `uv run python -m pytest tests/contract/test_hierarchy_path_rendering.py -q --no-cov`
Expected: PASS (existing movie/TV/music/podcast render tests unchanged — edition defaults None).

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/path_rendering.py tests/contract/test_hierarchy_path_rendering.py
git commit -m "feat: render movie edition token in the filename stem"
```

---

## Task 3: Thread edition through topology + validation movie context

**Files:**
- Modify: `src/chaos_librarian/topology.py` (`renderable_asset_context` passes `context.variant.edition`)
- Modify: `src/chaos_librarian/validation/rules/_common.py` (`_movie_renderable_context` reads raw `edition`)
- Modify: `src/chaos_librarian/engine/state.py` (`renderable_context_for_asset` MOVIE branch passes `edition=None` with a comment; see note)
- Test: `tests/contract/test_topology.py`, `tests/validation/...`

- [ ] **Step 1: Write the failing topology test**

```python
def test_renderable_asset_context_threads_movie_edition():
    from chaos_librarian.contract.domain import ParentKind
    from chaos_librarian.contract.scenario import EditionKind
    from chaos_librarian.topology import iter_asset_contexts, renderable_asset_context
    scenario = _movie_scenario_with_edition("directors_cut")  # via Scenario.model_validate
    ctx = next(iter_asset_contexts(scenario))
    rctx = renderable_asset_context(ctx, "library/movies")
    assert rctx.edition is EditionKind.DIRECTORS_CUT
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_topology.py -k edition -q --no-cov`
Expected: FAIL.

- [ ] **Step 3: Thread the field in `topology.renderable_asset_context`**

In `src/chaos_librarian/topology.py` `renderable_asset_context` (topology.py:242), add to the `RenderableAssetContext(...)` call:

```python
        edition=context.variant.edition,
```

`context.variant` is the scenario `Variant`, which now carries `edition` — no walker change needed.

- [ ] **Step 4: Thread the field in validation `_movie_renderable_context`**

In `src/chaos_librarian/validation/rules/_common.py` `_movie_renderable_context` (~line 2078), read the raw edition from the variant mapping and pass it. Use the existing `_enum` helper (tolerates None/absent):

```python
    edition = _enum(EditionKind, raw_context.variant.get("edition"))
    return RenderableAssetContext(
        ...
        edition=edition,
        ...
    )
```

Import `EditionKind` from `chaos_librarian.contract.scenario` in `_common.py`. Do NOT add edition to the episode/track/podcast raw contexts — the field is movie-only at render time. (`_enum(EditionKind, None)` returns None; verify `_enum`'s None-tolerance against its definition before relying on it.)

- [ ] **Step 5: Engine state MOVIE branch — explicit edition=None with invariant comment**

In `src/chaos_librarian/engine/state.py` `renderable_context_for_asset` MOVIE branch (state.py:274), the context is rebuilt from the **manifest** `ManifestVariant`, which has no `edition`. This method is only reached for **re-rendering** after a path/hierarchy action; no movie hierarchy action exists (and `relabel_edition` is deferred), so a movie asset never re-renders through here. Leave `edition` at its default `None` and add a one-line comment:

```python
        if variant.parent_kind is ParentKind.MOVIE:
            movie = self.movies[variant.parent_id]
            # No movie hierarchy/path action re-renders from manifest context, so
            # the edition (carried only on the scenario Variant) is not needed here;
            # initial seeding renders it via topology.renderable_asset_context.
            return RenderableAssetContext(
                ...  # edition defaults to None
            )
```

Do not add `edition` to `ManifestVariant` (that would bump the manifest schema). If a future `relabel_edition` action lands, the deferred follow-up must carry the edition into the manifest then.

- [ ] **Step 6: Run topology + validation tests**

Run: `uv run python -m pytest tests/contract/test_topology.py tests/validation -k "edition or movie" -q --no-cov`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/topology.py src/chaos_librarian/validation/rules/_common.py \
        src/chaos_librarian/engine/state.py tests/
git commit -m "feat: thread movie edition through topology and validation"
```

---

## Task 4: Fixtures — valid two-edition scenario + invalid collision

**Files:**
- Create: `tests/fixtures/scenarios/movie-editions.yaml` (valid)
- Create: `tests/fixtures/scenarios/invalid/movie-edition-path-collision.yaml`

- [ ] **Step 1: Add the valid two-edition fixture**

Create `tests/fixtures/scenarios/movie-editions.yaml` at `schema_version: 31`: one movie, two variants at the **same** resolution label but **different** editions (theatrical + directors_cut), distinct variant/bundle/asset ids (ids disambiguate entities; the edition only changes the rendered path). Empty `series`/`artists`; `timeline: []`. Model on `tests/fixtures/scenarios/duplicate-variant.yaml`. The two assets render to:
`<root>/Title - 1080p {edition-Theatrical}.mkv` and `<root>/Title - 1080p {edition-Director's Cut}.mkv` — distinct, so it validates clean. `tests/contract/test_sample_scenarios.py` will load it automatically.

- [ ] **Step 2: Add the invalid collision fixture**

Create `tests/fixtures/scenarios/invalid/movie-edition-path-collision.yaml`, first line `# expected: E_PATH_COLLISION`: one movie, two variants with the **same** label AND the **same** edition (or both edition omitted), distinct ids, so the rendered paths collide. `tests/validation/test_invalid_corpus.py` asserts the marker.

- [ ] **Step 3: Run the corpus + invalid-corpus tests**

Run: `uv run python -m pytest tests/contract/test_sample_scenarios.py tests/validation/test_invalid_corpus.py -q --no-cov`
Expected: PASS (valid fixture loads; invalid fixture reports `E_PATH_COLLISION`).

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/scenarios/movie-editions.yaml \
        tests/fixtures/scenarios/invalid/movie-edition-path-collision.yaml
git commit -m "test: movie edition fixtures (valid two-edition, collision)"
```

---

## Task 5: Regression + cross-cutting coverage

**Files:**
- Test: `tests/contract/test_hierarchy_path_rendering.py` (sidecar inheritance) + a regression assertion (existing topology/regression module or a new test)

- [ ] **Step 1: Sidecar-inherits-edition-stem test**

Add a test that a declared subtitle sidecar for an edition variant renders next to the edition media file. Either via `render_declared_sidecar_path` directly:

```python
def test_edition_sidecar_inherits_edition_stem():
    from chaos_librarian.path_rendering import render_declared_sidecar_path
    media = "library/movies/Orbit - 1080p {edition-Director's Cut}.mkv"
    assert render_declared_sidecar_path(media, "en", codec="srt") == (
        "library/movies/Orbit - 1080p {edition-Director's Cut}.en.srt"
    )
```

or via `build_initial_state` on a movie-with-edition-and-subtitle scenario asserting the seeded `ManifestSidecar.path` carries the token. Prefer the engine-level assertion if a sidecar-bearing movie fixture is easy to build; otherwise the direct call is sufficient (it is the exact function initial seeding uses at state.py:603).

- [ ] **Step 2: Backward-compat regression test**

Add a test asserting a no-edition movie scenario plus existing TV/music/podcast fixtures produce unchanged rendered paths and structurally identical manifests/journals (modulo embedded `schema_version`). Concretely, `build_initial_state` an existing no-edition fixture (e.g. `duplicate-variant.yaml`, re-pinned to 31) and assert no rendered `location.path` contains `{edition-`:

```python
def test_no_edition_scenario_has_no_edition_token():
    scenario = _load_fixture("duplicate-variant.yaml")
    manifest = build_initial_state(scenario, IdAllocator(TraceRecorder())).to_manifest()
    assert all("{edition-" not in loc.path for loc in manifest.locations)
```

Use the real `build_initial_state(scenario, ids)` arity with `IdAllocator(TraceRecorder())`, matching existing engine tests; confirm the helper imports against an existing engine test file before relying on them.

- [ ] **Step 3: Materialize/end-to-end path assertion**

Add (or extend) a test that drives a movie-with-edition scenario through the same initial-state/materialize path-assertion the other render tests use (no ffmpeg needed for the relative-path assertion) and asserts the on-disk relative path equals `<root>/<Title> - <label> {edition-<Name>}.<ext>`.

- [ ] **Step 4: Run full suite + full guardrail gate**

Run: `uv run python -m pytest -q --no-cov` then the full guardrail gate (including `schema_export --check`).
Expected: clean. Confirm `MANIFEST_SCHEMA_VERSION` is still 10 and `manifest.schema.json` is unchanged in `git diff`.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: lock edition sidecar stem and no-edition backward compat"
```

---

## Self-review checklist (run after implementing)

- Spec coverage: enum + optional field (T1), token render incl. apostrophe + role-suffix ordering + None-unchanged (T2), topology/validation threading + engine no-re-render note (T3), valid two-edition + collision fixtures (T4), sidecar stem inheritance + backward-compat regression + materialize path (T5). All covered.
- No new error code (reuses `E_PATH_COLLISION` via the unchanged `rule_rendered_path_collisions`).
- `EditionKind` is a closed enum; unknown value fails at parse (T1 negative test).
- `SCENARIO_SCHEMA_VERSION` 30 → 31 (literal `Literal[31]` hardcoded); `MANIFEST_SCHEMA_VERSION` stays 10; only `scenario.schema.json` regenerated.
- No new `ParentKind`, no new top-level tuple, no new model, no manifest field, no new timeline action.
- Edition reaches the path only via the scenario `Variant` at initial seeding; movie assets never re-render from manifest context.
- Follow-ups filed before merge: regional/free-form editions; `relabel_edition` action; Option-B multi-variant-edition layer.
