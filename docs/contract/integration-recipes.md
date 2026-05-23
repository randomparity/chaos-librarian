# Integration Recipes

These recipes describe consumer-neutral adapter usage. They intentionally avoid
application database details.

## Scanner Final-State

1. Run `chaos-librarian materialize scenario.yaml --out run-dir`.
2. Scan `run-dir/library/`.
3. Export `observed-state.json` with `observed_ref` and `current_path` for each
   observed asset.
4. Run:

```bash
chaos-librarian compare run-dir observed-state.json --mode final-state --json
```

Exit `0` means the scanner final state matches. Exit `6` means read the
divergence report.

## Prober Final-State

Use the scanner recipe, but include `content_hash` and `probed` for each asset.
The adapter compares hashes only when both sides supply them and compares probed
media only when both sides supply `probed`.

## Watcher Identity-History

Export either per-asset `path_history` or global `events` for observed path
mutations. Use:

```bash
chaos-librarian compare run-dir observed-state.json --mode identity-history --json
```

This mode still checks final state, then verifies durable identity through
path-affecting lifecycles such as moves, renames, slow copies, and delete/add
restores.

## Daemon Churn

For daemon-style churn tests, use `chaos-librarian run` fixtures when the daemon
needs wall-clock changes. Export observed state after the daemon settles and
compare it with the same command. Run-mode journal digests ignore volatile
`wall_clock_time` during fixture validation.

## Malformed Media

Malformed-media fixtures are opt-in and label their corruption evidence in both
the manifest and materialization report:

```bash
chaos-librarian materialize \
  tests/fixtures/scenarios/malformed-container-header.yaml \
  --out run-malformed-header \
  --json
```

Adapters should treat `manifest.current.json` as the oracle for identity,
location, and version lineage. `materialization.json.corruption_actions[]`
records the byte-level corruption audit trail and whether ffprobe failed as
expected or still parsed the output.

## CI Guidance

Fast CI should run small final-state fixtures with scanner/prober exports and
fail on compare exit `1`, `6`, or `7`.

Extended CI should add identity-history watcher fixtures, slow-copy cases,
delete/add restore cases, and run-mode churn fixtures.
