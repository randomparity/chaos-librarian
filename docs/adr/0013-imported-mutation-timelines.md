# ADR 0013: Bound imported mutation timelines to byte-preserving filesystem actions

## Status

Proposed — implementation awaits operator approval of the reviewed design.

## Context

Issue #233 adds opt-in chaos to imported scenarios. ADR0012 keeps imported bytes
and forbids track-aware rewrites. Existing synthetic fuzz lanes build their own
fixed-cardinality topology; imported scenarios can contain one arbitrary asset.

## Decision

Add an imported-topology entry point in the generation package, reusing named
`RngStreams` and existing event models. It accepts final imported assets and
reservations, emits a finite seeded sequence of rename/move/mtime events after
initial sidecars, and leaves default import unchanged. The importer owns output
publication and full validation. The CLI exposes opt-in plus seed/count controls.

## Consequences

A small imported-safe action subset works across movie/TV/music topology without
claiming synthetic fuzz-lane parity. Events preserve original media bytes and
avoid deletion lifecycle machinery. The existing scenario seed records the
selection seed; no schema expansion or new dependency is required.

## Considered & rejected

- **Reuse synthetic lane builders directly.** verified: at commit
  `096883227140e5a663a7b6db1120815e24c56e7f`, `generation/planner.py` required-event
  builders index multiple fixed assets while `plan_payload_parts` constructs a new
  synthetic library. Source inspection establishes the arbitrary-topology mismatch.
- **Generate a second synthetic library and merge it.** judgment: changes the
  imported topology and solves a broader problem than the requested follow-up.
- **Enable the full imported action set immediately.** judgment: adds lifecycle
  and mutation breadth without a coverage requirement; a bounded filesystem subset
  supplies replayable activity while preserving the ADR0012 track restrictions.
