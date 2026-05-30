# Scenario Recipe Library

Ready-to-run chaos-librarian scenarios that target known media-library failure
patterns. Each file is a complete, valid scenario you can run directly:

```bash
chaos-librarian validate recipes/scanner/deleted-midscan.yaml
chaos-librarian plan     recipes/scanner/deleted-midscan.yaml --out ./run/
```

Recipes are grouped by failure pattern under `recipes/<category>/`. Every recipe
carries a header comment describing what it tests, the expected consumer
response, and any required profile.

**Expected consumer response** is descriptive only — chaos-librarian is
policy-neutral and does not assert your application's outcome. It emits the
neutral oracle (journal + manifest); your consumer compares its own observed
state against that. The column records what a correct consumer *should* do:

- **converges** — settle on the correct end state with no duplicate or orphan entries.
- **errors** — surface a clear error for the affected asset (the file is unreadable).
- **diverges** — observed state legitimately differs from the oracle; the consumer
  should detect the mismatch rather than silently accept it.

## Schema version and bit-rot guard

Every recipe pins `schema_version: 24` (the current `SCENARIO_SCHEMA_VERSION`).
`tests/recipes/test_recipe_corpus.py` re-validates every recipe in CI and asserts
each category ships at least three. Because `schema_version` is a fixed literal
on the model, the next schema bump makes the recipes fail validation, turning the
corpus test red and forcing a deliberate update — recipes cannot rot silently.

## Recipes

### `scanner/` — scanner resilience
Filesystem changes a scanner must tolerate mid-scan.

| Recipe | Tests | Expected response | Requires |
| --- | --- | --- | --- |
| `deleted-midscan.yaml` | A tracked file is deleted mid-scan. | converges | none |
| `moved-during-scan.yaml` | A file is relocated within its root mid-scan. | converges | none |
| `renamed-during-scan.yaml` | A file is renamed in place mid-scan. | converges | none |
| `delete-then-restore.yaml` | A file disappears then reappears at a new path. | converges | none |

### `watcher/` — watcher/daemon stress
Copy races and network/filesystem timing artifacts.

| Recipe | Tests | Expected response | Requires |
| --- | --- | --- | --- |
| `slow-copy-race.yaml` | A slow copy is in flight; only the commit makes the final path visible. | converges | none |
| `rapid-churn.yaml` | Move, delete, and re-add fire back-to-back on one asset. | converges | none |
| `mtime-touch.yaml` | A bare mtime change with no content change. | converges | filesystem-artifacts |
| `nfs-lag-visibility.yaml` | A network mount delays a re-added file's visibility. | converges | network-fs-lag |

### `identity/` — durable identity through mutation
Identity must survive moves, renames, root changes, and container swaps.
(chaos-librarian has no content-hash dedup knob, so these exercise identity
survival, not collision authoring.)

| Recipe | Tests | Expected response | Requires |
| --- | --- | --- | --- |
| `move-and-rename.yaml` | Identity survives a move then a rename. | converges | none |
| `cross-root-move.yaml` | Identity survives a move between roots. | converges | none |
| `remux-container.yaml` | Identity survives a container swap (mkv→mp4). | converges | none |

### `metadata/` — metadata corruption
Corruption injected via profile-gated timeline events.

| Recipe | Tests | Expected response | Requires |
| --- | --- | --- | --- |
| `corrupt-container-header.yaml` | Container header overwritten; probe fails. | errors | malformed-media |
| `truncated-file.yaml` | File cut short mid-stream. | errors / diverges | malformed-media |
| `corrupt-packet-range.yaml` | A run of mid-stream video packets corrupted. | diverges | malformed-media |
| `wrong-oracle-hash.yaml` | Oracle records a deliberately wrong content hash. | diverges | negative-oracle |

### `sidecar/` — sidecar chaos
Subtitle, poster, and NFO sidecar behavior.

| Recipe | Tests | Expected response | Requires |
| --- | --- | --- | --- |
| `late-subtitle.yaml` | A subtitle sidecar materializes after the asset. | converges | none |
| `poster-and-nfo.yaml` | Non-subtitle companion sidecars (poster, NFO). | converges | none |
| `second-language-subtitle.yaml` | A French subtitle joins an existing English one. | converges | none |

### `archive/` — archive and discovery
Moving assets into archives and across roots.

| Recipe | Tests | Expected response | Requires |
| --- | --- | --- | --- |
| `archive-on-event.yaml` | An active asset is archived (default location). | converges | none |
| `archive-explicit-root.yaml` | An asset is archived into a named archive root. | converges | none |
| `relocate-then-archive.yaml` | An asset moves across roots, then is archived. | converges | none |
