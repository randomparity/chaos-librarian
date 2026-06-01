# Timeline Engine

`resolve_timeline` parses event `at` values and sorts events by logical time and
declaration order. The resolved order is the event order used by plan, step,
materialize, run, journal generation, and replay verification.

`step_boundaries` converts resolved events into user-visible step units.
Adjacent matching `slow_copy_start` and `slow_copy_commit` events count as one
step so `--steps N` and `--next N` do not stop inside a slow-copy pair.

`engine/events.py` dispatches timeline events and folds state deltas into
manifest state, version history, path history, and per-entity reports.
`engine/event_handlers/*` owns the action-family handlers that produce journal
entries and deterministic state deltas for the dispatcher.

`run_plan` builds the initial state, applies the selected timeline prefix,
builds `manifest.initial.json`, `manifest.current.json`, `journal.jsonl`,
`replay.json`, and report projections.

`write_fixture` publishes plan fixtures atomically through a staging directory.
It writes immutable source artifacts, mutable current artifacts, reports, and
the `.chaos-librarian-run` sentinel.

`append_step` is used by step mode. It rewrites mutable files atomically per
file and appends new journal lines for the newly applied events.

`replay_plan_bundle` consumes validation-prepared embedded scenario bytes,
checks deterministic run identity, verifies step boundaries, and compares the
journal digest for replay evidence.
