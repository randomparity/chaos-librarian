# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Chaos Librarian generates and mutates synthetic media libraries to give [voom-v2](https://github.com/randomparity/voom-v2) a fast, replayable test surface for scanners, watchers, media probes, durable identity, bundle tracking, and reconciliation. It models external library activity but does NOT know the application's database schema or expected policy outcomes — it emits neutral oracle journals and manifests that the application under test compares against its own observed state.

Design source of truth: [`docs/specs/chaos-librarian-design.md`](docs/specs/chaos-librarian-design.md). Consumer-facing contract: [`docs/contract/`](docs/contract/).

## Development rules

These rules apply to every task in this project unless explicitly overridden.
Bias: caution over speed on non-trivial work.

## Rule 1 — Architecture Trumps All
Project is pre-release, prioritize architectural correctness in design choices.
Good design leads to long project life.

## Rule 2 — Think Before Coding
State assumptions explicitly. Ask rather than guess.
Push back when a simpler approach exists. Stop when confused.

## Rule 3 — Simplicity First
Minimum code that solves the problem. Nothing speculative.
No abstractions for single-use code.

## Rule 4 — Surgical Changes
Touch only what you must. Don't improve adjacent code.
Match existing style. Don't refactor what isn't broken.

## Rule 5 — Goal-Driven Execution
Define success criteria. Loop until verified.
Strong success criteria let Claude loop independently.

## Rule 6 — Use the model only for judgment calls
Use for: classification, drafting, summarization, extraction.
Do NOT use for: routing, retries, deterministic transforms.
If code can answer, code answers.

## Rule 7 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.

## Rule 8 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
If unsure why existing code is structured a certain way, ask.

## Rule 9 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

## Rule 10 — Checkpoint after every significant step
Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.

## Rule 11 — Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you think a convention is harmful, surface it. Don't fork silently.

## Rule 12 — Fail loud
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

## Project state

Sprint 0 (`feat/sprint-0`, PR #5) is **contract-only**: it freezes seven JSON Schema artifacts and a Typer CLI surface, but ships no runtime behavior. `validate` is implemented as of Sprint 1. The other eight CLI commands are stubs that exit 1. Later sprints implement plan / materialize / run / step / replay / inspect / capabilities / clean.

Active per-sprint implementation plans live at `docs/superpowers/plans/`. No deferred-work issues are currently open.

## Architecture

### Schema source of truth

Pydantic v2 models in `src/chaos_librarian/contract/` are the schema source of truth. `src/chaos_librarian/schema_export.py` exports them to `schemas/*.schema.json` (JSON Schema draft 2020-12). CI runs `python -m chaos_librarian.schema_export --check` and fails on drift; engineers regenerate locally with `--write`.

Seven contract modules, one model file each:

- `scenario.py` — input YAML; timeline is a discriminated union on `action` (9 event variants)
- `manifest.py` — current expected library state
- `journal.py` — JSONL events; **discriminated union on `phase`** (atomic / started / progressed / committed / aborted)
- `replay_bundle.py` — `replay.json`; **discriminated union on `execution_mode`** (plan_only vs materialize/run). Embeds a second union: `ExecutionTraceEntry` is a discriminated union on `kind` (rng / alloc / materializer; `exit_code` required iff materializer).
- `validation.py`, `materialization.py`, `run_sentinel.py` — flat report schemas

`contract/paths.py` (security-critical) enforces `<run-dir>/library/` containment for every scenario path — strict subpath, rejects symlink escapes.

### Discriminated unions export as `oneOf`

`JournalEntry`, `ReplayBundle`, and `ExecutionTraceEntry` are `Annotated[<union>, Field(discriminator=...)]`. The two top-level unions are wrapped in `TypeAdapter(...)` in `schema_export.py` so the exported JSON Schema includes `oneOf` + `discriminator`; `ExecutionTraceEntry` is reached transitively through `ReplayBundle` and gets the same `oneOf` + `discriminator` treatment inside `$defs`. External consumers (voom-v2) see every mode-split contract natively rather than relying on Python-side validation. This pattern resolves the three high-severity findings from the Codex adversarial review of the Sprint 0 plan (commits `283b0a3`, `91964ea`) and the equivalent follow-up for `execution_trace` (issue #1).

### CLI

`src/chaos_librarian/cli/app.py` is a Typer app with 9 frozen commands. Every command name, argument, and option is part of the public contract — additions are allowed in later sprints, but renames/removals are breaking.

## Project-specific conventions

These differ from generic Python practice and tripped Sprint 0 implementers — preserve them:

- **Schema-version typing**: constants in `contract/__init__.py` are declared as bare `Final = 1` (no `[int]`) so `ty` infers `Literal[1]`. Each model writes `schema_version: Literal[1]` (hardcoded). Do NOT write `Literal[SCENARIO_SCHEMA_VERSION]` — `ty` rejects indirect `Literal[]` forms.
- **Enum classes**: use `class X(enum.StrEnum):`, not `class X(str, enum.Enum):` (ruff UP042).
- **Negative tests**: build a `dict` payload and call `Model.model_validate(payload)`. Don't construct invalid models with keyword args + `# type: ignore` — `ty` doesn't honor mypy-style ignores, and the project lints out stale `# noqa`.
- **`model_config = ConfigDict(extra="forbid")`** on every BaseModel class. Missing it would let scenario authors silently get away with typos.
- **Typer Path arguments**: use `Annotated[Path, typer.Argument(...)]`, not `Path = typer.Argument(...)` (ruff B008).
- **Absolute imports only** — ruff `flake8-tidy-imports` `ban-relative-imports = "all"`.

**After editing any model in `src/chaos_librarian/contract/`**: regenerate `schemas/` with `--write` and commit the updated artifacts in the same change. The drift gate will fail CI otherwise.

## Commands

```bash
uv sync                                                              # install/update deps
uv run pytest                                                        # full suite
uv run pytest tests/contract/test_journal.py -v                      # one file
uv run pytest tests/contract/test_journal.py::test_atomic_entry_roundtrip  # one test
uv run ruff check . && uv run ruff format --check .                  # lint + format check
uv run ty check src tests                                            # type check
uv run python -m chaos_librarian.schema_export --check               # schema drift gate
uv run python -m chaos_librarian.schema_export --write               # regenerate schemas/
uv run chaos-librarian --help                                        # CLI surface
prek run --all-files                                                 # pre-commit hooks
```

## Layout notes

- `schemas/` is generated but checked in — never hand-edit.
- `tests/fixtures/scenarios/*.yaml` are both example fixtures and the contract smoke-test corpus (`tests/contract/test_sample_scenarios.py` loads each through `Scenario.model_validate`).
- `tests/` mirrors `src/chaos_librarian/` structure (`tests/contract/` ↔ `src/chaos_librarian/contract/`, `tests/cli/` ↔ `src/chaos_librarian/cli/`).
