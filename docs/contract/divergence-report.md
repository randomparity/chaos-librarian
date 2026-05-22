# Divergence Report Contract

`divergence.schema.json` is the successful comparison output. A report with
`ok: false` means comparison ran and found differences; it is not a CLI error
envelope.

## Report Shape

Top-level fields:

- `schema_version`: `1`
- `run_id`
- `mode`: `final-state` or `identity-history`
- `ok`
- `fixture`: run directory, execution mode, asset count, journal count
- `observed`: consumer name/version, observed time, asset count
- `findings`

`ok` must equal `not any(finding.severity == "error")`. Validation rejects a
report where `ok` disagrees with the findings.

Each `DivergenceFinding` has:

- `code`
- `severity`
- `message`
- optional `oracle_asset_id`
- optional `oracle_event_id`
- `related_oracle_event_ids`
- optional `observed_ref`
- optional `expected`
- optional `observed`
- `evidence`

For grouped lifecycle findings, `oracle_event_id` is the first oracle event in
journal order and `related_oracle_event_ids` contains the remaining grouped
event ids in journal order.

## Codes

- `D_ASSET_MISSING`: oracle asset has no observed match.
- `D_ASSET_UNEXPECTED`: observed asset has no oracle match.
- `D_MATCH_AMBIGUOUS`: matching evidence is not one-to-one.
- `D_PATH_MISMATCH`: matched current paths differ.
- `D_DELETION_MISMATCH`: one side sees the asset as deleted and the other does not.
- `D_HASH_MISMATCH`: both sides supplied hashes and they differ.
- `D_PROBE_MISMATCH`: both sides supplied probed media and compared fields differ.
- `D_SIDECAR_MISSING`: oracle sidecar is missing from the observed asset.
- `D_SIDECAR_UNEXPECTED`: observed sidecar is absent from the oracle.
- `D_TOPOLOGY_MISMATCH`: matched work/variant/bundle structure differs.
- `D_IDENTITY_SPLIT`: one oracle lifecycle maps to different observed refs.
- `D_HISTORY_CONFLICT`: per-asset and global history evidence disagree.
- `D_HISTORY_MISSING`: expected identity-history evidence is absent.
- `D_HISTORY_UNEXPECTED`: observed history does not map to oracle history.

Sprint 9 emits `error` severity for all listed codes.

## CLI Exit Codes

`chaos-librarian compare` exits:

- `0` when the report is `ok: true`
- `6` when comparison succeeds but the report is `ok: false`
- `1` for adapter input errors such as malformed observed JSON or run-id mismatch
- `7` for missing or invalid run sentinels
