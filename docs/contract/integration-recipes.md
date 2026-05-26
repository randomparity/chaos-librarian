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

## VOOM CI Scenario Pack

The `tests/fixtures/scenarios/voom-ci/` pack gives consumer CI a stable set of
small fixtures that map to common scanner, prober, transcode policy, rescan,
and malformed-media checks. The fixtures stay consumer-neutral; VOOM-specific
exporters still own application database reads and policy assertions.

| Fixture | Consumer assertion | Command | Capability gate |
| --- | --- | --- | --- |
| `tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml` | Scanner/prober final state contains H.264 MP4, H.264 MKV, audio layout, and sidecar subtitle evidence. | `materialize` then `compare --mode final-state` | `ready_for.materialize_static` |
| `tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml` | HEVC policy can select H.264 MP4 and MKV inputs as transcode candidates. | `materialize` then consumer policy execution | `ready_for.materialize_static` |
| `tests/fixtures/scenarios/voom-ci/hevc-noop.yaml` | The same HEVC policy treats an HEVC MKV input as already compliant. | `materialize` then consumer policy execution | `ready_for.materialize_hevc_video` |
| `tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml` | A single deterministic reencode changes final probe/hash evidence for rescan loops. | `run --duration 2s --speed 20x` for live watchers, or `plan`/`step` for oracle-only stepping | `ready_for.materialize_media_mutations` |
| `tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml` | Malformed-media handling reports stable corruption metadata and expected adapter guidance. | `materialize` then inspect `materialization.json.corruption_actions[]` | `ready_for.materialize_media_mutations` |

Check gates with:

```bash
uv run chaos-librarian capabilities --json
```

The malformed fixture opts into the `malformed-media` profile in its YAML. There
is no separate `ready_for` field for that profile.

For mutation loops, materialized `step` is plan-only and rejects `materialize`
or `run` directories with `E_STEP_UNSUPPORTED_MODE`. Use `run` when the
consumer needs live filesystem changes, and use `plan` plus `step` only when a
test needs deterministic oracle snapshots without on-disk media.

## Duplicate And Variant Pack

Use this pack when a consumer needs duplicate-candidate and variant-topology
coverage without changing the baseline first-pack fixture:

```bash
chaos-librarian materialize \
  tests/fixtures/scenarios/duplicate-variant-expanded.yaml \
  --out run-duplicate-variant-expanded \
  --json
```

Recommended exports:

- Scanner recipe: export every asset with `observed_ref` and `current_path`.
  Current paths disambiguate the same-label duplicate variants and the duplicate
  assets inside one bundle.
- Prober recipe: add `content_hash` and `probed` for each asset. Equal hashes
  are duplicate-candidate evidence, not a policy command to merge records.
- Topology recipe: add work, variant, and bundle refs when the consumer tracks
  them. A pathless topology export can surface the ambiguous `Synthetic Echo`
  and `Synthetic Pair` keys, but `current_path: null` still means deleted; add
  paths or hashes before treating the compare result as a clean final-state
  check.

## Fuzz Profile Generation

Use fuzz profiles when a consumer needs deterministic variation without
hand-authoring every mutation:

```bash
uv run chaos-librarian generate \
  --profile fuzz-smoke \
  --seed 123 \
  --out fuzz-smoke.yaml \
  --json

uv run chaos-librarian generate \
  --profile fuzz-regression \
  --lane media-rewrite \
  --seed 457 \
  --out fuzz-regression-media-rewrite.yaml \
  --json

uv run chaos-librarian plan fuzz-smoke.yaml --out run-fuzz-smoke --json
```

The generated YAML carries `profiles: ["fuzz-smoke"]` and a `generation` block
with the profile, lane, profile version, seed, and static budget ceilings.
Timeline events are explicit after generation, so downstream commands do not use
hidden randomness. Replay never calls the generator; it reads the scenario source
stored in `replay.json`.

| Lane | Purpose |
| --- | --- |
| `smoke` | Small materialize-safe local scenario. |
| `core-fs` | Moves, renames, delete/add, archive, roots, and slow copy. |
| `media-rewrite` | Video, audio, container, and metadata rewrites. |
| `sidecar-subtitle` | Sidecar create/update/remove plus subtitle extract/embed. |
| `malformed` | Corrupt and malformed media events behind `malformed-media`. |
| `negative-oracle` | Intentional oracle mismatch events. |
| `filesystem-artifact` | Filesystem artifact events such as mtime touches. |
| `network-lag` | Run-mode lag windows for delayed visibility and rename behavior. |

`fuzz-smoke` is suitable for local and optional fast checks. `fuzz-regression`
is reserved for scheduled or maintainer-dispatched jobs.

## Watcher Identity-History

Export either per-asset `path_history` or global `events` for observed path
mutations. Use:

```bash
chaos-librarian compare run-dir observed-state.json --mode identity-history --json
```

This mode still checks final state, then verifies durable identity through
path-affecting lifecycles such as moves, renames, slow copies, and delete/add
restores.

## Network Filesystem Lag

The `network-fs-lag` profile is for `chaos-librarian run`, not `materialize`.
Lag fixtures describe explicit lag events and produce path-state windows.
Those windows include delayed visibility, delayed rename, and held-handle
evidence in `materialization.json.network_lag_actions[]`. Consumers should
compare watcher observations to those recorded windows, not to guessed sleeps
or low-level OS notification ordering.

The catalog run fixture exercises delayed rename, delayed visibility, and
held-handle lag windows under wall-clock execution:

```bash
uv run chaos-librarian run \
  tests/fixtures/scenarios/interceptor-catalog-run.yaml \
  --out /tmp/interceptors-run \
  --duration 2s \
  --speed 10x \
  --json
```

## Daemon Churn

For daemon-style churn tests, use `chaos-librarian run` fixtures when the daemon
needs wall-clock changes. Export observed state after the daemon settles and
compare it with the same command. Run-mode journal digests ignore volatile
`wall_clock_time` during fixture validation.

## Malformed Media

Malformed-media fixtures are opt-in and label their corruption evidence in both
the manifest and materialization report:

```bash
uv run chaos-librarian materialize \
  tests/fixtures/scenarios/malformed-container-header.yaml \
  --out run-malformed-header \
  --json
```

The interceptor catalog materialize fixture exercises the static fixture's
materialize-safe `truncate_file` and `touch_mtime` path:

```bash
uv run chaos-librarian materialize \
  tests/fixtures/scenarios/interceptor-catalog.yaml \
  --out /tmp/interceptors \
  --json
```

Adapters should treat `manifest.current.json` as the oracle for identity,
location, and version lineage. `materialization.json.corruption_actions[]`
records the corruption audit trail, including byte, packet, and metadata
evidence where applicable, and whether ffprobe failed as expected or still
parsed the output.

## Negative Oracle Hash

Use `negative-oracle` fixtures to prove a consumer validates hashes rather than
trusting fixture structure alone:

```bash
uv run chaos-librarian materialize \
  tests/fixtures/scenarios/negative-oracle-hash.yaml \
  --out /tmp/negative-oracle \
  --json

uv run chaos-librarian compare \
  /tmp/negative-oracle \
  observed-state.json \
  --mode final-state \
  --json
```

The observed-state export should include the consumer's actual file hash for
the affected asset. This recipe succeeds when `compare` reports
`D_HASH_MISMATCH` and exits with divergence code `6`; a success exit would mean
the negative-oracle check did not exercise the intended mismatch.

## CI Guidance

Fast CI should run small final-state fixtures with scanner/prober exports and
fail on compare exit `1`, `6`, or `7`. No performance profiles by default run
in this tier. `fuzz-smoke` may run only in a separate selectable job.

| Tier | Trigger | Profile coverage | Recommended coverage |
| --- | --- | --- | --- |
| Fast | Pull request and `main` push | No performance profiles by default; optional `fuzz-smoke`. | Small scanner/prober final-state fixtures. |
| Extended | Scheduled nightly or maintainer dispatch | `performance-smoke`, `performance-scale`, `fuzz-smoke`, `fuzz-regression` | Identity-history watcher fixtures, slow-copy cases, delete/add restore cases, and run-mode churn fixtures. |
| Stress | Manual release-candidate dispatch | `performance-stress` | Long wall-clock runs, cleanup validation, and large-library compare recipes. |

Performance profile labels are accepted by the scenario contract. Extended and
stress jobs must keep capability skips visible in test output and must fail
during setup when the runner lacks the selected profile's required free disk.
