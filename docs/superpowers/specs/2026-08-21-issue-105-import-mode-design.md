# Existing-Media Import Mode — Design (issue #105)

Date: 2026-08-21 · Status: Approved design for `feat/existing-media-import-105`
ADR: [0012 — Import assets materialize by copying scenario-bundled originals](../../adr/0012-import-file-reference-assets.md)

## Goal

`chaos-librarian import <input-dir>` scans a real media library, probes each
media file with ffprobe, detects sidecars, and emits a self-contained scenario
bundle — `scenario.yaml` plus a content-addressed `media/` directory — whose
materialization reproduces the original files byte-for-byte. Generated
scenarios pass `validate`, work in `plan` (plan-only preview), and materialize
with exact probed properties (ADR 0012 snapshot semantics).

## CLI surface

```
chaos-librarian import INPUT_DIR --out SCENARIO.yaml
    [--mode full|sample|dedup]   # default: full
    [--max-works N]              # cap total works (movies+series+artists+podcasts); no default cap
    [--max-variants N]           # cap variants per work; default 4
    [--max-duration-s SECONDS]   # skip files longer than N seconds; no default cap
    [--json]
```

- `--out` must not exist (mirrors `generate --out`); the `media/` bundle is
  created beside it (`<out-dir>/media/` where `<out-dir>` is `--out`'s parent).
- `sample` caps imports per category (detected container) at `--max-works`
  files per category in addition to the global work cap.
- `dedup` skips files whose sha256 was already imported (bundle is
  content-addressed, so dedup is a bundle-lookup, not a re-copy).
- Exit codes follow `docs/contract/cli-reference.md` conventions: 0 success,
  3 usage/input errors via `emit_cli_error(E_IMPORT_FAILED, ...)` envelope;
  `--json` prints a structured import report on success.

## Contract changes (scenario schema v32 → v33)

1. `Asset.import_source: ImportSource | None = None`, where
   `ImportSource = {path: str}`. `path` is relative, has safe components
   (`is_safe_path_component` per component), and resolves to a strict subpath
   of the scenario file's directory. Mutually exclusive with
   `same_content_as`/`hash_collision_with`/`hardlinked_to`/`symlink`
   (extend `_check_content_dedup_fields`).
2. An import asset must declare `video is None`, `audio == ()`,
   `subtitles == ()`, and all four synthesis knobs `None`
   (`mp4_moov_placement`, `matroska_muxing_profile`, `embedded_chapters`,
   `embedded_cover_art`) — model validator on `Asset`.
3. `CreateSidecarEvent.body` is allowed for `kind=subtitle` (byte-exact
   imported `.srt`/`.ass` text); validator `_check_fields_match_kind`
   widens accordingly. NFO/CUE unchanged; posters stay synthesized.
4. `SCENARIO_SCHEMA_VERSION = 33`; `Scenario.schema_version: Literal[33]`;
   regenerate `schemas/scenario.schema.json`.

## Validation changes

- New rule `rule_import_source` (`E_IMPORT_SOURCE_INVALID`, new code):
  - `import_source.path` shape: relative, safe components, no `..`,
    resolves strictly under the scenario file's directory, symlink-resolved
    (reject escapes through symlinks).
  - Timeline media-mutation events (`reencode_video`, `reencode_audio`,
    `remux_container`, `embed_subtitle`, `extract_subtitle`) targeting an
    import asset are rejected (`E_MATERIALIZE_UNSUPPORTED` — checked inside
    `rule_materialize_media_matrix`, which already owns "materialize can't do
    this").
- No existing rule rejects import scenarios: empty-of-tracks assets pass
  `rule_materialize_media_matrix` (nothing declared to check), and no rule
  requires a non-empty timeline. `rule_hierarchy_invariants` and
  `rule_rendered_path_collisions` apply unchanged.

## Materializer changes

- `materialize_assets_phase_a` dispatch order: `symlink` → `hardlinked_to` →
  `same_content_as` → `import_source` → full synthesis. New
  `_copy_import_asset` in `materializer/content/synthesis.py`:
  1. Resolve `scenario_dir / import_source.path` with the same containment
     check the validation rule uses (defense in depth; materializer re-checks).
  2. `shutil.copyfile` to the rendered library path.
  3. sha256, `probe_file`, `MaterializedAsset` with probed size/duration.
  4. `ContentSourceEvidence(provider="import-file", source="import",
     origin_uri=<bundle-relative path>, content_hash=sha256:...)`,
     `cache_disposition=NOT_CACHEABLE`.
- Missing bundle file at materialize time → `MaterializationError` with a new
  `E_IMPORT_SOURCE_MISSING` code routed through the existing materialization
  error envelope.
- `source_capabilities.collect_content_source_capabilities()` gains an
  `import-file` provider entry (available iff ffprobe present; no network, no
  cache).

## Importer module (`src/chaos_librarian/importer/`)

New package, four focused units:

- `scan.py` — walk `INPUT_DIR` (skipping symlinks to dirs and hidden dirs),
  classify files by extension against `SUPPORTED_CONTAINERS` plus subtitle
  (`.srt`, `.ass`, `.ssa`), NFO (`.nfo`), CUE (`.cue`), and poster extensions
  (`.jpg`, `.jpeg`, `.png`, `.webp` with poster-ish names: `poster*`,
  `folder*`, `cover*`). Unrecognized files are reported as skipped.
- `probe_input.py` — wraps `materializer.tooling.probe.probe_file` for input
  files; computes sha256 for bundle naming/dedup. Files that fail probing are
  reported as skipped with the probe error, never abort the whole import.
- `topology.py` — maps probed files onto the scenario hierarchy:
  - Video file directly under a `Season NN` directory (case-insensitive) →
    series episode; series name = grandparent dir; `SxxEyy` parsed from the
    filename (`season_folders` layout, `sxxexx_title` naming).
  - Any other video file → movie: multiple video files in one directory
    become variants of one movie (`movie_folder`); lone videos at the scan
    root become `movie_flat` movies titled from the filename stem.
  - Audio file under `<Artist>/<Album>[/Disc NN]/` → artist/album(/disc)/track
    (`artist_album_disc` layout); audio at the scan root is skipped with a
    reported reason (no convention to anchor it).
  - Podcasts are not detected (issue sketch names movies, TV, flat
    collections only).
  - Sidecars attach to the nearest video in the same directory with a
    matching stem (`<stem>.<lang>.srt` → language from suffix, default
    `en`; `<stem>.nfo`; `<stem>.cue`; poster files attach per directory).
- `emit.py` — builds the scenario payload dict (mirroring
  `generation/api.py::_generate_scenario_yaml_unvalidated` structure:
  `schema_version`, `scenario_id` (`import-<input-dirname>-<yyyymmddhhmm>`),
  `seed: 0`, `duration_scale: "normal"`, no `profiles`/`generation`,
  `library.roots = [{id: "main", path: "<sanitized input-dirname>"}]`),
  stages bundle files (`media/<sha256>.<container>`, copied with
  `shutil.copyfile`), emits timeline `create_sidecar` events for detected
  sidecars, writes YAML via the same ruamel dump style, then runs the emitted
  YAML through `Scenario.model_validate` before reporting success (an import
  that cannot re-validate is a hard error).

Asset IDs: `imp-<sha256[:12]>` plus `-<k>` suffix when the same content
appears as multiple assets (full mode duplicates). Deterministic for a given
scan order (sorted paths).

### Import report (human + `--json`)

```json
{
  "scenario_path": "...", "bundle_dir": "...",
  "files_scanned": N, "files_imported": N,
  "files_skipped": [{"path": "...", "reason": "..."}],
  "works": {"movies": N, "series": N, "artists": N},
  "sidecars": {"subtitles": N, "nfo": N, "cue": N, "posters": N},
  "bundle_bytes": N, "warnings": ["..."]
}
```

## Data flow

```
INPUT_DIR ──scan──▶ candidates ──ffprobe+sha256──▶ probed files
   ──topology──▶ movies/series/artists + sidecar events
   ──emit──▶ <out>/scenario.yaml + <out>/media/<sha>.<ext>
   ──(later) materialize──▶ library/<root>/... (byte copies) ──probe──▶ manifest
```

## Error handling

| Failure | Behavior |
|---|---|
| `INPUT_DIR` missing/not a dir | Typer `exists=True` argument error |
| `--out` exists | `E_IMPORT_FAILED` (path taken), exit 3 |
| No media files found | `E_IMPORT_FAILED` ("no importable media found"), exit 3 |
| Individual file unprobesable | skipped, reported, import continues |
| Bundle copy fails (I/O) | `E_IMPORT_FAILED` with path, exit 3; partial bundle files removed |
| Re-validation of emitted YAML fails | `E_IMPORT_FAILED` (internal invariant), exit 3 |
| Bundle file missing at materialize | `E_IMPORT_SOURCE_MISSING` materialization error |
| ffprobe missing entirely | `E_IMPORT_FAILED` ("ffprobe not available"), exit 3 |

## Threat model (security-relevant change)

**Boundary inventory.** New boundary: an untrusted `scenario.yaml` names a
file (`import_source.path`) that the materializer reads and copies into the
library. This *widens* the existing input surface — today scenario paths only
name library outputs, never process-read inputs.

**Actor model.** The untrusted party is whoever authors a scenario YAML (the
files circulate as test fixtures between people/machines). The local operator
running `chaos-librarian` is trusted; the process runs with the operator's
rights.

**Controls.**
- `import_source.path` must be relative with per-component
  `is_safe_path_component` validation (no separators, no `..`, no control
  chars) — same primitive `paths.py` uses for library paths.
- The resolved path must be a strict subpath of the scenario file's own
  directory, checked with symlink resolution (`Path.resolve()`), so a YAML
  cannot escape its bundle via symlinks — mirroring `resolve_under_library`'s
  symlink handling. Enforced at validate time AND re-checked at materialize
  time.
- Absolute paths and home-relative shortcuts are rejected by the relative-path
  rule; the worst case is reading a file the author already shipped alongside
  the YAML.
- Bundle files are copied, never executed; the only tool invoked on them is
  ffprobe (already required by materialize).

**Out of scope.** Content attacks inside media files (malformed containers
that exploit ffprobe/consumers) are the *point* of the feature — chaos-librarian
is a test-fixture generator for exactly such media; sandboxing ffprobe is not
attempted. Disk-exhaustion via huge bundles is bounded only by the CLI caps
(documented), not enforced.

## Testing

- **Contract**: import-asset validators (exclusivity, no-tracks, knob ban);
  `body` on subtitle sidecars; schema export drift (regenerate + `--check`).
- **Validation**: `rule_import_source` — escape (`../`), absolute, control
  chars, symlink escape, mutation-event rejection; corpus fixtures under
  `tests/fixtures/scenarios/invalid/` with `# expected: E_...` markers.
- **Importer unit tests**: fixture trees (movie folder, season folders,
  artist/album, flat, sidecars, unrecognized files, unprobesable file) scanned
  with a stub prober (no ffprobe dependency in unit tests); mode/cap behavior;
  deterministic IDs; bundle layout.
- **Materializer**: `_copy_import_asset` copies bytes, records evidence,
  probes output; missing bundle file → `E_IMPORT_SOURCE_MISSING`.
- **End-to-end (real-tool, `tests/integration/*_real.py`)**: import a small
  generated-by-ffmpeg fixture library, `validate` the scenario (criterion 2),
  `plan` it (criterion 5), `materialize`, and assert the materialized file's
  probe equals the original's probe (criterion 3) and sidecars exist
  (criterion 4).
- **CLI**: `--json` report shape, exit codes, `--help` order test update,
  `docs/contract/cli-reference.md` row (doc-pinning test).

## Exclusions (frozen)

- `--add-chaos` flag — deferred (operator decision 2026-08-21; tracked issue).
- `manifest.json` emission — deferred (same).
- Podcast topology detection, media-mutation events on import assets — not in
  acceptance criteria; file follow-up issues if surfaced during review.
