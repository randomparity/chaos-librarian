# Troubleshooting

## `E_YAML_PARSE`

Read the reported scenario path and YAML parser message. Fix indentation,
quoting, and collection syntax before checking field-level errors.

## Shape Errors

`E_FIELD_MISSING`, `E_FIELD_UNKNOWN`, `E_FIELD_LITERAL`, and `E_FIELD_TYPE`
mean the scenario shape does not match the contract. Compare the reported path
with `docs/user/scenario-authoring.md` and the JSON Schema artifact.

## `E_PATH_CONTAINMENT`

Keep all scenario paths under `<run-dir>/library/`. Avoid absolute paths,
`..` traversal, and symlink escapes.

## `E_LIFECYCLE_INVALID`

Check event ordering for `add_file`, `delete_file`, `move_asset`, and
slow-copy events. Examples include adding an already placed asset, operating on
an asset after delete, or committing a slow copy without a matching start.

## Exit `4`

Install or upgrade ffmpeg or ffprobe. Run:

```bash
uv run chaos-librarian capabilities --json
```

If `ready_for.materialize_media_mutations` is false, install or upgrade
mkvmerge before enabling media-mutation jobs.

## Exit `5`

Inspect `materialization.json` and the recorded external tool invocation
details. This usually points to a synthesis, probe, filesystem, or media
mutation failure.

## Exit `6`

Inspect replay or compare divergence output. Replay divergence means the
recorded bundle did not reproduce the expected oracle. Compare divergence means
the consumer export differs from the run oracle.

## Exit `7`

Verify the run directory has a valid `.chaos-librarian-run` sentinel and that
all paths remain within the protected library root.
