# Replay Bundle

`replay.json` is a single JSON file sufficient to reproduce a run. Plan-only
bundles are bit-identical across runs and platforms; materialize bundles are
logically identical modulo volatile fields. See
[`chaos-librarian-design.md` "Replay Bundle"](../specs/chaos-librarian-design.md).

## Mode-Split Fields

- **`run_id`** — UUIDv5 derived from
  `uuid5(CHAOS_LIBRARIAN_NAMESPACE_UUID, "<scenario_hash>:<seed>")` in plan-only
  mode; random UUIDv4 in materialize/run.
- **`created_at`** — **omitted entirely** in plan-only (field absent from JSON,
  not null); RFC 3339 in materialize/run.

## Volatile Fields (Materialize / Run)

The following fields are excluded from materialize-mode equivalence comparison:

- `created_at`, any `wall_clock_time` on journal entries
- `run_id` (UUIDv4 in these modes)
- content hashes and probed media facts
- the `toolchain` block
