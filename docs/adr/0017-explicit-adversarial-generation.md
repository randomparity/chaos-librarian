# ADR 0017: Explicit adversarial generation lane

## Status

Accepted (2026-10-25 operator approval for issue #248).

## Context

Epic #244 needs bounded combined generation after #245–#247, while ordinary
profiles must remain unchanged unless opted in.

## Decision

Add `adversarial-media` to allowed `fuzz-regression` lanes through existing
`--lane`. Omit it from the canonical default lane cycle. Reuse existing budgets,
validation, materialization and replay, with recipe-specific coverage cells.

## Consequences

The scenario enum extension requires schema version 37 and fixture migration.
An explicit seed-248 corpus reaches the supported cases without changing the
ordinary lane cycle. No new scheduler or mutation framework is needed.

## Considered & rejected

- Add recipes to the default malformed lane. judgment: violates the requested
  opt-in boundary and changes ordinary generated scenarios.
- Add a separate profile or runner. judgment: duplicates existing selection,
  budgets and equipped CI machinery without serving another criterion.
- Do nothing. judgment: leaves #248 fixed-seed combined coverage unmet.
