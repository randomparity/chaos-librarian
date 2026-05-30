# ADR 0001: Batch `generate` — seed derivation and lane distribution

- **Status:** Accepted (2026-05-29)
- **Context issue:** #104

## Context

The single-scenario `generate` command shipped on the coverage-led **lane**
architecture (see `docs/superpowers/specs/2026-05-25-fuzz-generation-suite-design.md`),
which deliberately rejected open-ended weighted fuzzing and deferred a public
batch/suite command. Issue #104 asks for batch generation and sketches a
different surface: `--count`, `--seed`, and a `--timeline-weight` knob selecting
named "timeline strategies" (`balanced`, `heavy-churn`, `heavy-corruption`,
`sidecar-focused`, `network-lag`, `mixed`).

The strategy names overlap almost one-for-one with existing lanes (`core-fs`,
`malformed`, `sidecar-subtitle`, `network-lag`, …). We need batch generation that
is deterministic, keeps each scenario individually reproducible, and does not
introduce a second coverage-control mechanism alongside lanes.

## Decision

1. **Layer `--count N` onto lanes.** Batch mode is a CLI/orchestration layer over
   the unchanged single-scenario generator. No Pydantic model or JSON Schema
   changes.
2. **Seed derivation is `seed_i = seed + i`** for item `i` in `0..count-1`.
   Transparent and individually reproducible: item `i` equals
   `generate --lane lane_i --seed seed_i`.
3. **Lane distribution:** with an explicit `--lane`, every item uses it; for
   `fuzz-regression` with no `--lane` and `count > 1`, items cycle a fixed
   `CANONICAL_FUZZ_LANES` tuple; `fuzz-smoke` always uses `smoke`. For
   `fuzz-regression` with no `--lane` and `count == 1`, the existing
   `--lane is required` error is preserved.
4. **No `--timeline-weight` option.** Lanes already partition timeline coverage
   by action family.
5. **`--out` is a file when `count == 1` (current contract) and an existing
   directory when `count > 1`.** Files are named `<scenario_id>.yaml`.
6. **All-or-nothing pre-write:** generate+validate all items and pre-check
   collisions before writing any file.

## Consequences

- The current single-file `generate` contract is preserved exactly at the
  default `count == 1`; existing contract tests are unchanged.
- Batch output is a pure function of `(profile, seed, count[, lane])`, satisfying
  #104's determinism criterion, and unique `seed_i` values guarantee
  collision-free file names.
- One coverage-control concept (lanes) instead of two; the `--timeline-weight`
  acceptance-criterion item is intentionally not implemented, documented here and
  in the spec.
- `seed_i = seed + i` means two batches with overlapping `[seed, seed+count)`
  ranges and the same lane produce overlapping files — expected and deterministic,
  not a defect.
- A TOCTOU window remains between collision pre-check and write; it fails loudly
  via atomic `os.link` rather than overwriting. Not closed (the single-scenario
  path has the same property).

## Considered & rejected

- **Implement `--timeline-weight` strategies literally (per #104 sketch).**
  Rejected: duplicates the shipped, tested lane system and contradicts the
  fuzz-generation-suite decision to be coverage-led rather than weighted. Two
  overlapping knobs (`--lane` and `--timeline-weight`) would confuse the contract
  and double the surface to test.
- **Add `--timeline-weight` as a within-budget event-count scale.** Rejected for
  the initial change as speculative: no user need is established for varying
  event density independently of lane, and lane budgets already set event counts.
  Can be revisited as a separate issue if a need appears.
- **Hash-derived sub-seeds (`hash(seed, i)`) instead of `seed + i`.** Rejected:
  opaque and not individually reproducible with the existing single-file
  `generate --seed` command. The collision-resistance it buys is unnecessary
  because `seed + i` is already collision-free across a single batch.
- **Always treat `--out` as a directory (even for `count == 1`).** Rejected:
  breaks the committed single-file `--out` contract and its tests for no benefit.
- **Per-lane independent seed streams (advance seed only within a lane).**
  Rejected: makes item `i`'s seed depend on how many prior items shared its lane,
  which is harder to reproduce by hand than a flat `seed + i`.
- **Stream writes without an all-or-nothing pre-check.** Rejected: a mid-batch
  generator/validation failure would leave a partially populated directory,
  violating fail-loud expectations.
- **Close #104 as already satisfied by the lane command + CI seed manifest.**
  Rejected: users explicitly need one-shot batch generation; the manifest is a CI
  mechanism, not an interactive command.
