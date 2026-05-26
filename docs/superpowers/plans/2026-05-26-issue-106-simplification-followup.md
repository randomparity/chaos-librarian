# Issue 106 Simplification Review Follow-Up Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the low-risk simplification review recommendations from the
Issue 106 media hierarchy branch without changing scenario, journal, manifest,
or observed-state behavior.

**Architecture:** Keep hierarchy action knowledge owned by the contract layer,
keep validation projection refactors deferred until they can be shared across
rules, and remove local duplication only where the existing test surface can
prove behavior remains stable.

**Tech Stack:** Python 3.13, uv, pytest, ruff, ty.

---

## Review Decisions

Implement now:

- Add a shared `HIERARCHY_TIMELINE_ACTIONS` contract constant and use it from
  validation, materializer, engine path history, and adapter identity history.
- Replace hierarchy enum parser wrappers with the existing generic enum parser.
- Preserve sentinel-specific adapter errors with an explicit exception handler
  instead of class-name string matching.
- Copy slow-copy staging files with `shutil.copyfile` instead of loading the
  whole source file into memory.

Defer to GitHub issues:

- Reuse the engine report builder for adapter fallback report derivation
  (#121).
- Build report indexes once when generating per-entity reports (#120).
- Centralize validation current-path projection across slow-copy,
  path-containment, and hierarchy checks (#123).
- Share validation sidecar projection between sidecar target and lifecycle
  checks (#122).
- Share renderable asset context construction between engine, materializer, and
  tests (#126).
- Share report-family metadata between adapter report loading and materializer
  report writing (#127).
- Validate `remux_container.to_container` with the same container path syntax
  rules as initial asset containers (#124).
- Group renderer-derived sidecars once per hierarchy event instead of scanning
  all sidecars for each affected asset (#125).

## Tasks

- [x] Add red tests for the shared hierarchy action constant and slow-copy
      copy behavior.
- [x] Add the contract hierarchy action constant and replace local action sets.
- [x] Delete duplicate validation enum parser wrappers.
- [x] Replace adapter sentinel class-name matching with explicit exception
      handling.
- [x] Replace slow-copy `read_bytes`/`write_bytes` with `shutil.copyfile`.
- [x] File GitHub issues for all valid deferred recommendations.
- [x] Run focused tests, schema drift check, lint, and type check.
