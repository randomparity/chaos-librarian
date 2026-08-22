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
- `sample` caps imports at `--max-works` media files per detected container
  (counted pre-topology, on the sorted candidate list) in addition to the
  global work cap; the per-category cap is applied first, so a file dropped
  by it reports `cap:max_works_sample` even when the global cap is also
  exhausted.
- `dedup` skips files whose sha256 was already imported (bundle is
  content-addressed, so dedup is a bundle-lookup, not a re-copy).
- Skip/cap semantics are deterministic and observable: candidates are
  processed in sorted-path order; anything dropped by a mode, a cap
  (`--max-works`, `--max-variants`, `--max-duration-s`), or dedup lands in
  `files_skipped` with a distinct reason (`mode:duplicate`,
  `cap:max_works`, `cap:max_works_sample` (sample-mode per-category drops),
  `cap:max_variants`, `cap:max_duration_s`, `topology:no_anchor`,
  `topology:duplicate_episode`, `sidecar_duplicate`);
  partial series/artists are emitted as-is; sidecars attach only to
  imported videos — a sidecar whose video was skipped is itself skipped
  with reason `orphaned_sidecar`. When several imported videos in one
  directory share a stem, an ambiguous sidecar attaches to the
  lexicographically first matching video in sorted-path order.
- Exit codes follow `docs/contract/cli-reference.md`: `--out` handling
  reuses `validate_new_out_path` (existing `--out` or bad parent →
  `typer.BadParameter`, exit 2, same as `generate`); import-specific
  operational failures (no media found, staging/write/rollback errors,
  re-validation invariant) use `emit_cli_error(E_IMPORT_FAILED, ...)`
  (new envelope code declared beside `E_GENERATE_FAILED` in
  `cli/_envelope.py`)
  with exit 1; ffprobe missing or too old exits 4 (the documented
  external-tool code); `--json` prints a structured import report on
  success.

## Contract changes (scenario schema v32 → v33)

1. `Asset.import_source: ImportSource | None = None`, where
   `ImportSource = {path: str}`. `path` is relative, non-empty (at least
   one safe component), has safe components
   (`is_safe_path_component` per component), and resolves to a strict subpath
   of the scenario file's directory. Mutually exclusive with
   `same_content_as`/`hash_collision_with`/`hardlinked_to`/`symlink`
   (extend `_check_content_dedup_fields`).
2. An import asset must declare `video is None`, `audio == ()`,
   `subtitles == ()`, and all four synthesis knobs `None`
   (`mp4_moov_placement`, `matroska_muxing_profile`, `embedded_chapters`,
   `embedded_cover_art`) — model validator on `Asset`. The required
   `container`/`duration_seconds` fields are populated from the probe and
   bundle extension and are recorded metadata only; materialization and
   oracle comparison read the actual copied bytes.
3. `CreateSidecarEvent.body` is allowed for `kind=subtitle` (byte-exact
   imported subtitle text); validator `_check_fields_match_kind`
   widens accordingly. NFO/CUE unchanged; posters stay synthesized.
   Imported subtitle events carry `codec` mapped from the detected
   extension (`.srt`→`srt`, `.ass`→`ass`, `.ssa`→`ssa`) so the rendered
   sidecar extension matches the body; `encoding` stays default utf-8;
   `source` stays default. `rule_create_sidecar_content` skips its
   codec×source matrix check when `body` is present (the body is
   authoritative). The materializer gains a body branch in the phase-B
   subtitle write path (`_write_subtitle_sidecar`,
   `materializer/phase_b/media/handler.py`), writing `body` bytes verbatim
   instead of calling `subtitle_payload_bytes` when `body` is set. Phase-A
   declared-sidecar rendering never sees a body: declared subtitle tracks
   carry no body field and import assets forbid subtitles.
4. `SCENARIO_SCHEMA_VERSION = 33`; `Scenario.schema_version: Literal[33]`;
   regenerate `schemas/scenario.schema.json`.

## Validation changes

- New rule `rule_import_source` (`E_IMPORT_SOURCE_INVALID`, new code):
  - `import_source.path` shape, enforced LEXICALLY at validate time
    (rule_import_source never touches the filesystem — validation rules in
    general resolve against synthetic roots): must be relative, every
    component passes `is_safe_path_component`, no `..` — which together
    prove resolution strictly under the scenario file's directory without
    FS access. Existence and symlink-escape are re-checked at materialize
    time only, where the scenario directory is real (a replay-bundle
    RunInput has no on-disk directory; validate stays shape-only there too).
- `rule_materialize_media_matrix` early-returns for import assets (skipping
  its must-declare-video and audio-cardinality checks, which would otherwise
  reject a track-less asset) and additionally rejects timeline events
  `reencode_video`, `reencode_audio`, `remux_container`, `embed_subtitle`,
  `extract_subtitle` targeting an import asset (`E_MATERIALIZE_UNSUPPORTED`):
  their handlers and validation rules assume declared tracks in matrix
  vocabulary; on a declaration-free asset they are unvalidated territory.
  This is a closed classification — all other events operate on existing
  bytes without consulting track declarations and remain allowed.
  After the early-return, no remaining matrix check applies to import assets
  (there is nothing declared to check).
  Preflight capability gates get the same treatment:
  `assert_capable_for_webm_video` gates on `container == "webm"` alone today,
  so it must skip import assets (a copied .webm needs no libvpx-vp9).
  No existing rule rejects import scenarios otherwise, and no rule requires a
  non-empty timeline. `rule_hierarchy_invariants` and
  `rule_rendered_path_collisions` apply unchanged.

- `materialize_assets_phase_a` dispatch order: `symlink` → `hardlinked_to` →
  `same_content_as` → `import_source` → full synthesis. New
  `_copy_import_asset` in `materializer/content/synthesis.py`:
  1. Resolve `scenario_dir / import_source.path` with the same containment
     check the validation rule uses (defense in depth; materializer re-checks).
  2. `shutil.copyfile` to the rendered library path.
  3. sha256, `probe_file`, `MaterializedAsset` with probed size/duration.
  4. `ContentSourceEvidence` for the copy: `provider="import-file"`,
     `source="import"`, `asset_id=<the asset's id>`, `track_kind=VIDEO`
     for video containers / `AUDIO` for audio-only containers,
     `recipe_digest=sha256:<source file digest>` (the digest of the copied
     bytes — it identifies the exact content the "recipe" produced),
     `origin_uri=<bundle-relative path>`,
     `content_hash=sha256:<materialized bytes digest>`,
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
  classify files by extension against a real-library media vocabulary —
  video `{mkv, mp4, webm, avi, mov, ts, m4v, wmv, mpg, mpeg}`, audio
  `{flac, mp3, m4a, wav, ogg, opus}` (a deliberate widening beyond
  `SUPPORTED_CONTAINERS`: import exists for files the synthesis matrix
  cannot represent; `Asset.container` is free-form and import assets skip
  the matrix rule) — plus subtitle (`.srt`, `.ass`, `.ssa`), NFO (`.nfo`),
  and poster extensions (`.jpg`, `.jpeg`, `.png`, `.webp` with poster-ish
  names: `poster*`, `folder*`, `cover*`). `.cue` sheets are deliberately
  NOT detected: they accompany audio, and audio topologies have no sidecar
  attachment path in this slice (a `.cue` file is reported as skipped
  `unrecognized`). Extension matching is case-insensitive. Files with
  unrecognized extensions are reported as skipped (`unrecognized`);
  media-extension files that fail ffprobe are skipped with reason
  `probe_failed` and never abort the run.
- `probe_input.py` — wraps `materializer.tooling.probe.probe_file` for input
  files; computes sha256 for bundle naming/dedup.
- `topology.py` — maps probed files onto the scenario hierarchy:
  - Video file directly under a `Season NN` directory (case-insensitive) →
    series episode; series name = grandparent dir; `SxxEyy` parsed from the
    filename (`season_folders` layout, `sxxexx_title` naming). A filename
    with no parseable `SxxEyy` is skipped with reason `topology:no_anchor`;
    a second file with the same `SxxEyy` in one season is skipped with
    reason `topology:duplicate_episode`. A `Season NN` directory directly
    at the scan root has no grandparent to anchor a series name, so its
    files are also skipped with reason `topology:no_anchor`.
  - Any other video file → movie: multiple video files in one directory
    become variants of one movie (`movie_folder`); lone videos at the scan
    root become `movie_flat` movies titled from the filename stem.
  - Audio file under `<Artist>/<Album>[/Disc NN]/` → artist/album(/disc)/track
    (`artist_album_disc` layout); audio at the scan root or directly under
    an artist directory (no album layer) is skipped with reason
    `topology:no_anchor`.
  - Podcasts are not detected (issue sketch names movies, TV, flat
    collections only).
  - Sidecars attach to the nearest video in the same directory with a
    matching stem (`<stem>.<lang>.srt` → language from suffix, default
    `en`; `<stem>.nfo`; poster files attach per directory).
    When several imported videos in one directory share a stem, an
    ambiguous sidecar attaches to the lexicographically first matching
    video in sorted-path order. Attachments dedupe per
    (video, kind, language): the first sidecar in sorted-path order wins;
    later duplicates are skipped with reason `sidecar_duplicate` (so
    `Movie.srt` + `Movie.en.srt` imports one subtitle event, never a
    duplicate `(target, language)` pair).
  - Undetected sidecar-like files (`.vtt`, `.sub`/`.idx`, `.ttml`,
    non-poster images) are ignored and reported as skipped.
  - Entity ids never derive from titles alone: each emitted movie/series/
    artist id is `<slug>` from its directory name plus a `-<n>` suffix when
    two works would share an id, assigned in sorted-path order.
- `emit.py` — builds the scenario payload dict (mirroring
  `generation/api.py::_generate_scenario_yaml_unvalidated` structure:
  `schema_version`, `scenario_id` (`import-<input-dirname>-<yyyymmddhhmm>`),
  `seed: 0`, `duration_scale: "normal"`, no `profiles`/`generation`,
  `library.roots = [{id: "main", path: "<sanitized input-dirname>"}]`),
  stages bundle files (`media/<sha256>.<container>`, copied with
  `shutil.copyfile`), emits timeline `create_sidecar` events for detected
  sidecars, writes YAML via the same ruamel dump style, then runs the emitted
  YAML through the full validation pipeline (`run_validation` — shape plus
  every semantic rule, so criterion 2 holds at emit time, not just
  `Scenario.model_validate`) before reporting success (an import
  that cannot re-validate is a hard error).
  Emitted timeline events are fully determined: each `create_sidecar` id is
  `sidecar-<asset-id>-<n>` (per-asset counter in sorted sidecar order);
  every event carries `at: "0s"` — imported sidecars exist from the start of
  the run, so no clock or seed participates; a per-directory poster targets
  that directory's lexicographically first imported asset (sorted variant
  order).

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
  "sidecars": {"subtitles": N, "nfo": N, "posters": N},
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
| `--out` exists / bad parent | `typer.BadParameter` via `validate_new_out_path`, exit 2 (same as `generate`) |
| No media files found | `E_IMPORT_FAILED` ("no importable media found"), exit 1 |
| Individual file unprobesable | skipped, reported, import continues |
| Bundle copy fails, YAML write fails, or re-validation fails | `E_IMPORT_FAILED` with path, exit 1; rollback removes the emitted `scenario.yaml` and exactly the bundle file names this run staged (tracked list) on every post-staging failure — never a directory sweep, since `<out-dir>/media/` may hold entries shared with a sibling scenario's bundle |
| Bundle file missing at materialize | `E_IMPORT_SOURCE_MISSING` materialization error |
| ffprobe missing entirely | capability-style error, exit 4 (documented external-tool code) |

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
- At validate time the path is checked lexically only (relative, safe
  components, no `..` — which proves containment under the scenario dir
  without filesystem access). At materialize time the resolved real path is
  re-checked with symlink resolution (`Path.resolve()`), so a YAML cannot
  escape its bundle via symlinks — mirroring `resolve_under_library`'s
  symlink handling.
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
- **Validation**: `rule_import_source` — escape (`../`), absolute, empty
  path (`import_source: {path: ""}`), control
  chars, mutation-event rejection (lexical shape tests only — rules never
  touch the filesystem); corpus fixtures under
  `tests/fixtures/scenarios/invalid/` with `# expected: E_...` markers.
  Symlink-escape and missing-bundle cases are materializer-level tests.
- **Materializer**: `_copy_import_asset` copies bytes, records evidence,
  probes output; missing bundle file → `E_IMPORT_SOURCE_MISSING`; the
  subtitle-body write path in both phase-A and phase-B; skip/cap reason
  taxonomy (`mode:duplicate`, `cap:max_variants`, `orphaned_sidecar`).
- **Importer unit tests**: fixture trees (movie folder, season folders,
  artist/album, flat, sidecars, unrecognized files, unprobesable file) scanned
  with a stub prober (no ffprobe dependency in unit tests); mode/cap behavior;
  deterministic IDs; bundle layout.
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
