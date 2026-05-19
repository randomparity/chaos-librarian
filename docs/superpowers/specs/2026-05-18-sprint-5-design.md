# Sprint 5 — Materializer Capability Detection And Static Materialization

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Materialize Mode", §"Content Sources", §"Materializer Backends", §"Sprint 5", §"Schema Contract", §"Filesystem Safety".
**Predecessor:** Sprint 4 (`feat/sprint-4`, merged in #10) shipped the plan-only CLI surface end-to-end (`plan`, `step`, `inspect`, `clean`, `replay`) plus per-entity reports. Sprint 5 begins on top of that stack.
**Target branch:** `feat/sprint-5`.

## Goal

Begin the materialize half of the CLI contract. Sprint 5 ships:

1. `chaos-librarian capabilities --json` — detect ffmpeg, ffprobe, mkvtoolnix and enforce minimum versions.
2. `chaos-librarian materialize scenario.yaml --out <run-dir> --json` — produce a real on-disk library by synthesizing each asset from a seeded content recipe, then probe and hash it.
3. Seven content sources (Mandelbrot, color bars, solid color, sine, silence, channel-identity tones, generated SRT) and the FFmpeg invocations to mux them into mkv/mp4.

Sprint 5's materialize accepts **static scenarios only** (empty timeline). Mutation-bearing scenarios fail at materialize time with `E_MATERIALIZE_TIMELINE_UNSUPPORTED` (exit 5). Sprint 6 lifts the restriction for filesystem mutations; Sprint 7 for media mutations.

## Design Decisions Resolved In Brainstorming

The source design doc leaves several Sprint-5 specifics open. Each is resolved below; push back if you disagree before the plan is written.

1. **Materialize scope.** Static library only. `materialize` rejects any scenario with a non-empty timeline. The error is `E_MATERIALIZE_TIMELINE_UNSUPPORTED` (exit 5). Sprint 5 ships a new static-library scenario fixture to exercise the path because none of the first scenario pack qualifies (all entries use mutations).

2. **Replay scope.** `replay` stays plan-only-only this sprint. `ReplayBundle` gains a `MaterializeReplayBundle` variant so the contract is stable, but `replay_materialize_bundle` is **not** implemented — the CLI raises a structured `MaterializeReplayNotImplemented` (exit 1) when given a materialize bundle. The canonicalization rule for cross-toolchain equivalence ships as a pure helper (see "Layer 4 tests") but is not exercised against a second toolchain in Sprint 5; Sprint 9's voom-v2 adapter will be the first real consumer.

3. **Capability gate.** `capabilities` exits 0 when ffmpeg and ffprobe both meet their minimums (regardless of mkvtoolnix), exit 4 otherwise. `materialize` re-runs the same gate at startup and exits 4 with the identical JSON payload if it regressed since the standalone command. Minimum versions:
   - ffmpeg ≥ 7.0 (required)
   - ffprobe ≥ 7.0 (required)
   - mkvtoolnix ≥ 80 (optional in Sprint 5; reported but not required)

4. **`capabilities` output shape.**
   ```json
   {
     "schema_version": 1,
     "ffmpeg":     {"found": true,  "version": "7.1.1", "path": "/opt/homebrew/bin/ffmpeg",  "meets_minimum": true},
     "ffprobe":    {"found": true,  "version": "7.1.1", "path": "/opt/homebrew/bin/ffprobe", "meets_minimum": true},
     "mkvtoolnix": {"found": false, "version": null,    "path": null,                         "meets_minimum": false},
     "platform": "darwin-arm64",
     "ready_for": {
       "materialize_static": true,
       "materialize_filesystem_mutations": true,
       "materialize_media_mutations": false
     }
   }
   ```
   `ready_for` is a forward-looking signal so adapter authors can skip Sprint 6/7 tests cleanly when the toolchain isn't ready.

5. **Manifest schema strategy.** Sprint 0 already placed `content_hash: str | None = None` on `ManifestVersion` (`src/chaos_librarian/contract/manifest.py:47`) — Sprint 5 is the first sprint to *populate* it but does not add it. The new field is `probed: ProbedMedia | None = None`, also on `ManifestVersion` (versions identify concrete bytes; hashes and probed facts belong together). Adding `probed` is structural, so `MANIFEST_SCHEMA_VERSION` bumps `1 → 2`. Plan-only manifests serialize both fields as absent (Pydantic `model_dump(exclude_none=True)` — already the writer's convention), preserving Sprint 3's bit-identical-plan-only guarantee. Materialize manifests populate both. Both modes share one model. `ManifestSidecar` also gains `content_hash: str | None = None` so SRT sidecars carry hash provenance; the field stays None in plan-only and on non-text sidecars.

6. **`ProbedMedia` shape.** Drawn from `ffprobe -show_format -show_streams -of json`:
   ```python
   class ProbedStream(BaseModel):
       kind: Literal["video", "audio", "subtitle"]
       codec: str
       language: str | None = None
       width: int | None = None         # video-only
       height: int | None = None        # video-only
       fps: float | None = None         # video-only
       channels: int | None = None      # audio-only
       sample_rate: int | None = None   # audio-only
       default: bool | None = None      # subtitle-only
       forced: bool | None = None       # subtitle-only

   class ProbedMedia(BaseModel):
       container: str
       duration_seconds: float
       size_bytes: int
       streams: list[ProbedStream]
   ```
   Co-located in `contract/manifest.py` — it's a manifest-domain type even though materialization populates it.

7. **Same-toolchain bit-exactness.** Every FFmpeg invocation receives `-fflags +bitexact -flags +bitexact -map_metadata -1 -metadata creation_time=1970-01-01T00:00:00Z` plus muxer-deterministic flags appropriate to the container. On a fixed FFmpeg version on a fixed platform, two materialize runs of the same scenario+seed produce **byte-identical** library files and matching content hashes. Cross-toolchain hashes stay descriptive per the source design doc (`docs/specs/chaos-librarian-design.md:533`); the canonicalization rule strips them before comparison.

8. **Sprint 5 container/codec/resolution/audio matrix.**
   - Containers: `mkv`, `mp4`. (WebM, AVI deferred to Sprint 7.)
   - Video codecs: `h264` only (libx264 with bit-exact tune).
   - Resolutions: `sd` (640×480), `hd` (1280×720), `1080p` (1920×1080). 4K deferred.
   - Audio codecs: `aac` only.
   - Channel layouts: `mono`, `stereo`, `5.1`.
   - Sample rate: 48000 Hz (fixed for Sprint 5).
   - Subtitle codecs: `srt` only, sidecar mode only. `embedded` subtitle mode and the `embed`/`extract` mutations are Sprint 7.
   - Durations: 1–30 seconds. Anything longer is rejected to keep the test suite under the 50 MB cap (`docs/specs/chaos-librarian-design.md:646`).

   Scenarios outside this matrix fail with `E_MATERIALIZE_UNSUPPORTED` (exit 5) **at materialize time only**. They pass plan-only `validate` because plan-only is media-agnostic, matching the source doc's "scenarios are validated against available capabilities before materialization" (`docs/specs/chaos-librarian-design.md:765`).

9. **Scenario contract change.** Sprint 0's `scenario.schema.json` has `VideoTrack.source: str` (free-form) and no `source` field on audio or subtitles. Sprint 5 needs all three to drive recipe selection. Resolution: bump `SCENARIO_SCHEMA_VERSION: 1 → 2`. The new fields:
   - `VideoTrack.source: VideoSource` — enum-narrowed from `str`. Values: `mandelbrot`, `color_bars`, `solid_color`, `noise`.
   - `AudioTrack.source: AudioSource = AudioSource.SINE` — new with default. Values: `sine`, `silence`, `channel_tones`.
   - `SubtitleTrack.source: SubtitleSource = SubtitleSource.GENERATED_SRT` — new with default. Values: `generated_srt`.

   The defaults preserve every existing fixture (`tests/fixtures/scenarios/*.yaml`) — `VideoTrack.source` was already populated; audio and subtitle gain defaulted enum fields. `noise` stays in `VideoSource` because `slow-copy.yaml` uses it, but the Sprint 5 materializer rejects it with `E_MATERIALIZE_UNSUPPORTED`; Sprint 6+ implements it.

10. **Failure model: fail-fast with best-effort cleanup.** If asset *k*'s materialization fails, the orchestrator stops the loop, records the failure (asset_id, stage, exit_code, stderr_tail, invocation_index) in `MaterializationReport.failures`, runs `shutil.rmtree(out_dir / "library")` to remove partial bytes, writes the metadata files atomically with `outcome != "success"`, and exits 5. The sentinel is preserved so `clean` accepts the run-dir. Alternative options considered (continue-past-failures; two-pass dry-run-then-commit) are noted under "Alternatives Rejected".

11. **`MaterializeReplayBundle` shape (contract only).** Carries everything plan-only does plus `toolchain: ToolchainInfo`, `platform: str`, and `created_at: datetime`. `run_id` is a random UUIDv4 (not the deterministic UUIDv5 used in plan-only). `applied_events` is constrained to `0` in Sprint 5 (timeline is always empty). `replay <materialize-bundle>` exits 1 with a structured "not yet implemented" payload; the variant exists so the schema artifact is stable for Sprint 6+ readers.

12. **Reports — `AssetReport` bumps, others unchanged.** `reports/` is still built by Sprint 4's `engine.reports.build_report_set(initial, current, journal)` helper. `AssetSnapshot` (the leaf type embedded in `AssetReport`) gains `content_hash: str | None = None` and `probed: ProbedMedia | None = None` so adapter consumers see the materialized facts without joining back through `manifest.versions[]`. That structural change bumps `ASSET_REPORT_SCHEMA_VERSION: 1 → 2`. `WorkReport`, `VariantReport`, and `BundleReport` carry only id lists (no embedded snapshots) and stay at v1. Sprint 4's `reports.py` module docstring explicitly anticipates this (`src/chaos_librarian/contract/reports.py:4-5`).

13. **Run-dir recovery from crashes.** `RunSentinel` gains a `state: Literal['in_progress', 'complete'] = 'complete'` field. Sprint 0's plan-only flow writes `state: 'complete'` directly (no in-progress phase for plan-only — it writes everything in one staging-rename). Materialize writes `state: 'in_progress'` at the start of synthesis and replaces it with `state: 'complete'` as part of the final atomic batch. `RUN_SENTINEL_SCHEMA_VERSION` bumps 1 → 2. Consumers: `inspect` reports the state; `clean` accepts both states; `step` refuses `in_progress` with an `E_SENTINEL_IN_PROGRESS` error (exit 7); `materialize <run-dir>` refuses an existing `in_progress` directory (user must `clean` it first).

## Architecture

Single PR on `feat/sprint-5`. The engine stays pure plan-only; a new `materializer/` sibling package adds byte production. Composition is one-directional: materializer imports engine, never the reverse.

### New modules

```
src/chaos_librarian/materializer/
  __init__.py                  # re-exports detect_capabilities, materialize_scenario,
                               # MaterializeArtifacts, materialization-specific exceptions
  capabilities.py              # detect_capabilities() -> Capabilities; version parsing
  recipes.py                   # FFmpegInput + recipe_* per content source; srt_payload(...)
  ffmpeg.py                    # build_command(asset, recipes, output_path) -> argv;
                               # run_ffmpeg(cmd) -> ToolInvocation
  probe.py                     # probe_file(path) -> ProbedMedia
  run.py                       # materialize_scenario(scenario, out_dir, caps) -> MaterializeArtifacts
  writer.py                    # materialize-specific atomic write (composes engine.writer for metadata)
  errors.py                    # MaterializationError hierarchy

src/chaos_librarian/contract/
  capabilities.py              # Capabilities + ToolStatus + ReadyFor Pydantic models
```

### Modified modules

```
src/chaos_librarian/contract/
  __init__.py                  # adds CAPABILITIES_SCHEMA_VERSION = 1; bumps:
                               #   MANIFEST_SCHEMA_VERSION         1 -> 2
                               #   MATERIALIZATION_SCHEMA_VERSION  1 -> 2
                               #   REPLAY_BUNDLE_SCHEMA_VERSION    2 -> 3
                               #   SCENARIO_SCHEMA_VERSION         1 -> 2
                               #   ASSET_REPORT_SCHEMA_VERSION     1 -> 2
                               #   RUN_SENTINEL_SCHEMA_VERSION     1 -> 2
                               # (WORK_/VARIANT_/BUNDLE_REPORT_SCHEMA_VERSION stay at 1)
  scenario.py                  # VideoSource/AudioSource/SubtitleSource enums; source fields on
                               # AudioTrack and SubtitleTrack with defaults; VideoTrack.source enum-narrowed
  manifest.py                  # ProbedMedia + ProbedStream; ManifestVersion gains probed (content_hash
                               # already at v1); Manifest.schema_version Literal[2]
  materialization.py           # fills in MaterializationReport with started_at/finished_at, platform,
                               # ToolchainInfo, MaterializedAsset, MaterializationFailure; schema_version Literal[2]
  replay_bundle.py             # adds MaterializeReplayBundle variant to the execution_mode discriminated
                               # union; schema_version Literal[3]; ReplayBundle TypeAdapter union extended
  reports.py                   # AssetSnapshot gains content_hash + probed; AssetReport.schema_version
                               # Literal[2]; other three report classes unchanged
  run_sentinel.py              # adds state field; schema_version Literal[2]

src/chaos_librarian/schema_export.py
                               # adds capabilities.schema.json to the drift gate; regenerates the
                               # six bumped schemas (manifest, materialization, replay-bundle,
                               # scenario, asset-report, run-sentinel)

src/chaos_librarian/cli/app.py
                               # real `capabilities` body; real `materialize` body; both reach into
                               # materializer/ via stable public API
```

### Generated artifacts

```
schemas/
  capabilities.schema.json     # NEW: v1
  manifest.schema.json         # REGEN: v2 (ManifestVersion gains probed; content_hash already at v1)
  materialization.schema.json  # REGEN: v2 with filled-in report shape
  replay-bundle.schema.json    # REGEN: v3 with MaterializeReplayBundle variant in oneOf
  scenario.schema.json         # REGEN: v2 with audio/subtitle source enums
  asset-report.schema.json     # REGEN: v2 with content_hash + probed on AssetSnapshot
  run-sentinel.schema.json     # REGEN: v2 with state field
  # work-report / variant-report / bundle-report stay at v1
```

`schema_export.py --check` runs in CI and fails on drift. Engineers regenerate locally with `--write` and commit the updated artifacts in the same change.

### Composition: how a materialize run flows

```
chaos-librarian materialize scenario.yaml --out fixtures/run-001
  cli/app.py:materialize
    detect_capabilities()                        # exit 4 on failure
    validate_scenario(scenario)                  # exit 3 on validation failure
    materializer.materialize_scenario(...)
      step 1: refuse non-empty timeline          # E_MATERIALIZE_TIMELINE_UNSUPPORTED, exit 5
      step 2: containment gate                   # E_PATH_CONTAINMENT, exit 7
      step 3: re-run detect_capabilities         # exit 4 on regression
      step 4: engine.run_plan(scenario, steps_limit=0)
              -> initial manifest, empty journal, plan-only-style replay shape
              (the plan-only run_id from this call is discarded; materialize
              assigns a fresh UUIDv4 at the start of step 6)
      step 5: pre-flight matrix check            # E_MATERIALIZE_UNSUPPORTED, exit 5
      step 6: synthesis loop (per asset)
                build FFmpegInput recipes via materializer.recipes
                write SRT sidecars first
                build_command(...) -> argv
                run_ffmpeg(argv) -> ToolInvocation             # E_MATERIALIZE_TOOL_FAILED, exit 5
                probe_file(asset_path) -> ProbedMedia          # E_MATERIALIZE_PROBE_PARSE_FAILED, exit 5
                content_hash = sha256_hex(asset_path)
                augment manifest asset
      step 7: atomic metadata write              # sentinel + manifests + journal + reports + replay.json
      step 8: return MaterializeArtifacts
    cli writes --json payload to stdout, exits 0
```

Failure at any subprocess step in step 6: stop the loop, record the failure, `shutil.rmtree(out_dir / "library")`, write metadata atomically with `outcome != "success"`, exit 5.

## Capability Detection

`materializer/capabilities.py` shells out to each tool with `--version`, parses the first line, normalizes via `packaging.version.Version`, and returns a `Capabilities` model. Used by two callers: the `capabilities` CLI command and `materialize` startup.

### Detection algorithm (per tool)

1. `shutil.which(name)` → path or None. None → `ToolStatus(found=False, version=None, path=None, meets_minimum=False)`.
2. `subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)`. Timeout → not-found semantics with a structured warning.
3. Parse the first line against a tool-specific regex:
   - ffmpeg: `r"^ffmpeg version (\S+)"` — matches `ffmpeg version 7.1.1 Copyright ...` and `ffmpeg version n7.1-0ubuntu1`.
   - ffprobe: `r"^ffprobe version (\S+)"`.
   - mkvtoolnix: `r"^mkvmerge v(\S+)"` (we probe `mkvmerge` as the canonical front-end and report as `mkvtoolnix`).
4. Extract the upstream-version triplet from the captured group via `_canonical_version_from_tool_output(raw: str) -> Version | None`. The helper applies in order:
   ```python
   m = re.match(r"^[nN]?(\d+(?:\.\d+){0,2})", raw)
   if not m:
       return None        # unparseable — treat as malformed-output not-found
   return Version(m.group(1))
   ```
   This handles `7.1.1`, `n7.1-0ubuntu1` → `7.1`, `7.0.2-3ubuntu1` → `7.0.2`, `n7.0` → `7.0`. Git-snapshot builds like `N-118412-g0ce1c8f7c5` return `None` and the tool is reported as found-but-malformed (`meets_minimum: false`).
5. `meets_minimum = parsed_version >= MIN_VERSIONS[tool]` — only evaluated when the helper returned a `Version`; a `None` result short-circuits to `meets_minimum: false`.

```python
MIN_VERSIONS: Final = {
    "ffmpeg":     Version("7.0"),
    "ffprobe":    Version("7.0"),
    "mkvtoolnix": Version("80"),
}
```

### Public API

```python
def detect_capabilities() -> Capabilities: ...

def assert_capable_for_static_materialize(caps: Capabilities) -> None:
    """Raise CapabilityGateError (exit 4) if ffmpeg or ffprobe fails its gate."""
```

### `capabilities` CLI

```python
@app.command()
def capabilities(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    caps = detect_capabilities()
    if json_output:
        typer.echo(caps.model_dump_json(indent=2, exclude_none=True))
    else:
        _render_capabilities_human(caps)
    raise typer.Exit(code=0 if caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum else 4)
```

The body output is the full `Capabilities` JSON in both success and failure cases — humans and agents can read the structured reason regardless of exit code.

### `ready_for` semantics

```python
ready_for = ReadyFor(
    materialize_static                = ffmpeg_ok and ffprobe_ok,
    materialize_filesystem_mutations  = ffmpeg_ok and ffprobe_ok,                  # Sprint 6
    materialize_media_mutations       = ffmpeg_ok and ffprobe_ok and mkvtoolnix_ok, # Sprint 7
)
```

These flags are forward-looking. Sprint 5 itself only consults `materialize_static`.

## Content Sources And Recipes

Seven sources, one pure function per source in `materializer/recipes.py`. Each takes a seed-derived parameter blob and returns an `FFmpegInput` (lavfi expression + extra flags) or, for SRT, returns bytes that the orchestrator writes to a sidecar file. No subprocess work happens in `recipes.py`.

```python
@dataclass(frozen=True, slots=True)
class FFmpegInput:
    lavfi: str | None              # e.g. "mandelbrot=size=1920x1080:rate=24:start_scale=2.7"
    file_path: Path | None         # for srt sidecar input case
    extra_flags: tuple[str, ...] = ()

def recipe_mandelbrot(width, height, fps, duration_s, seed) -> FFmpegInput:
    start_scale = _scale_from_seed(seed)  # deterministic mapping
    return FFmpegInput(
        lavfi=f"mandelbrot=size={width}x{height}:rate={fps}:start_scale={start_scale}",
        extra_flags=("-t", str(duration_s)),
    )

def recipe_color_bars(...): ...    # smptebars
def recipe_solid_color(...): ...   # color=c=<hex>:s=<W>x<H>:r=<fps>; hex from seed
def recipe_sine(...): ...          # sine=frequency=<f>:duration=<d>:sample_rate=48000; freq from seed
def recipe_silence(...): ...       # anullsrc=channel_layout=<lay>:sample_rate=48000
def recipe_channel_tones(...): ... # one distinct frequency per channel (220/440/880 Hz pattern)

def srt_payload(language: str, duration_s: float, seed: int) -> str:
    """Pure: returns SRT body. Orchestrator writes it to a sidecar path."""
```

Per-asset seeds flow through Sprint 2's RNG: `scenario_seed.stream("content").substream(asset_id)`. Two scenarios with the same seed get the same Mandelbrot focus, the same solid-color hex, the same sine frequency.

## FFmpeg Command Builder

`materializer/ffmpeg.py:build_command(asset, video, audios, subtitles, output_path)` returns argv. Always includes the bit-exact flag set and chooses muxer-deterministic flags appropriate to the container. Unsupported combos raise `UnsupportedMaterializationError` before any subprocess starts.

```python
BITEXACT_FLAGS: Final = (
    "-fflags", "+bitexact",
    "-flags", "+bitexact",
    "-map_metadata", "-1",
    "-metadata", "creation_time=1970-01-01T00:00:00Z",
)
```

`run_ffmpeg(cmd, timeout_s=60)` is the subprocess wrapper. It captures `stderr_tail` (last 2 KB, UTF-8 lossy), records a `ToolInvocation` with command/exit_code/duration_ns, and never lets ffmpeg inherit stdin.

## Manifest Augmentation

After each successful synthesis the materializer finds the `ManifestVersion` corresponding to the just-written asset (one version per asset in Sprint 5 since there are no mutations) and sets both fields:

```python
version = next(v for v in manifest.versions if v.asset_id == asset.id)
version.content_hash = "sha256:" + sha256_hex(asset_path.read_bytes())
version.probed       = probe_file(asset_path)
```

`probe.probe_file(path)` invokes `ffprobe -show_format -show_streams -of json` and maps the result into the `ProbedMedia` Pydantic model. Stream subtype fields (width/height for video, channels for audio, default/forced for subtitle) are set only on the matching `kind`; the others stay `None`.

For each sidecar produced during synthesis (SRT subtitles in Sprint 5), the materializer writes the file to `<run-dir>/library/<path>`, then sets `ManifestSidecar.content_hash` to `sha256:<hex>` of the file bytes. Sprint 5 does NOT run ffprobe on sidecars and does NOT add subtitle streams to the asset's `probed.streams[]` — sidecar subtitles are separate files, not embedded streams. The asset's `probed.streams[]` includes only video and audio streams in Sprint 5; embedded subtitles arrive in Sprint 7 when `subtitle_mode: embedded` becomes a supported value.

## Atomic Write And Failure Cleanup

`materializer/writer.py` composes `engine.writer` (which writes metadata files to a temp directory and renames into place) and adds the materialize-specific bits: the `library/` tree (FFmpeg writes there directly during synthesis) and `materialization.json`.

**Run-dir allocation is lazy.** Steps 1-5 of the orchestrator (timeline scope, containment, capability gate, engine pass, matrix pre-flight) run entirely in memory. They emit stdout JSON on failure and exit without ever touching the filesystem under `out_dir`. The run-dir is created at the start of step 6, with the sentinel written first **with `state: 'in_progress'`**, just before the synthesis loop begins to spawn FFmpeg subprocesses. Synthesis runs. On success, the final atomic batch writes all metadata files AND replaces the sentinel with `state: 'complete'` via the same temp-dir-rename mechanism. On a clean failure path (caught subprocess error or probe error), the cleanup wipes `library/` and writes the metadata files; the sentinel is replaced with `state: 'complete'` because the materialization terminated cleanly with a recorded failure. Only an uncaught crash (signal, power loss) leaves the sentinel at `state: 'in_progress'`; this is the marker future tooling uses to detect interrupted runs. This means:

- Pre-synthesis failures (exits 3, 4, 5-from-timeline, 5-from-matrix, 7-from-containment) leave **no on-disk artifact**. The user sees the failure on stdout and there is nothing to `clean` up.
- Synthesis-time failures (exit 5 from tool failure or probe parse error) leave a partial run-dir with a valid `state: 'complete'` sentinel, an empty `library/` tree (wiped per the cleanup rule), and a `materialization.json` describing what happened.
- Uncaught crashes (SIGTERM, power loss) leave the sentinel at `state: 'in_progress'` with whatever partial library bytes had been written; `inspect` reports the state, `step` refuses with `E_SENTINEL_IN_PROGRESS` (exit 7), and `clean` accepts the directory for removal.

The "atomic" guarantee for the success path: **if `manifest.current.json` is present, all of metadata is present**, and the library bytes it references are present. During synthesis, partial library bytes may exist on disk but no consumer can mistake the run for finished — `manifest.current.json` is written last, in one atomic rename batch that also flips the sentinel to `state: 'complete'`.

### Failure cleanup

On any exit-5 failure during synthesis:

1. Stop the synthesis loop. Do not attempt subsequent assets.
2. Record the failure in `MaterializationReport.failures`.
3. `shutil.rmtree(out_dir / "library")` — wipe everything under the library root. Safe because containment has been enforced; nothing outside `library/` was ever written.
4. Write the metadata files atomically with the appropriate `outcome` value (`tool_failed`, `unsupported`, `containment_violation`). The manifest's `manifest.current.json` includes only the un-augmented (no content_hash, no probed) asset records — readers learn materialization failed via `outcome` and via the presence of `failures[]`.
5. CLI exits 5.

`chaos-librarian inspect <run-dir>` reads the diagnostics; `chaos-librarian clean <run-dir>` removes the fixture (sentinel is intact, so clean accepts it).

## Error Model

| code | when                                                  | error_code(s) |
|------|-------------------------------------------------------|---------------|
| 0    | success                                               | — |
| 2    | usage error (Typer-handled)                           | — |
| 3    | scenario validation failed                            | E_* from validation pipeline |
| 4    | required tool missing or below minimum                | E_MATERIALIZE_CAPABILITY_GATE |
| 5    | materializer ran but produced an error                | E_MATERIALIZE_TIMELINE_UNSUPPORTED, E_MATERIALIZE_UNSUPPORTED, E_MATERIALIZE_TOOL_FAILED, E_MATERIALIZE_PROBE_PARSE_FAILED |
| 7    | containment violation; or in-progress sentinel        | E_PATH_CONTAINMENT, E_SENTINEL_IN_PROGRESS |

Exits 1 and 6 are not reachable from Sprint 5 production paths (`replay <materialize-bundle>` returns exit 1 only because there's nothing else to do; divergence is plan-only-only).

### Exit-5 outcome mapping in `materialization.json`

`outcome` values that never `write` in Sprint 5 are reserved in the schema for forward compatibility — Sprint 6+ may introduce synthesis-time matrix rejection that would write them.

| error_code                            | `outcome` field         | writes materialization.json? |
|---------------------------------------|-------------------------|------------------------------|
| E_MATERIALIZE_TIMELINE_UNSUPPORTED    | `unsupported`           | no (pre-flight)              |
| E_MATERIALIZE_UNSUPPORTED             | `unsupported`           | no (pre-flight)              |
| E_MATERIALIZE_TOOL_FAILED             | `tool_failed`           | yes                          |
| E_MATERIALIZE_PROBE_PARSE_FAILED      | `tool_failed`           | yes                          |
| E_MATERIALIZE_CAPABILITY_GATE         | `tool_missing`          | no (pre-flight, exit 4)      |
| E_PATH_CONTAINMENT (at materialize)   | `containment_violation` | no (pre-flight, exit 7)      |

### JSON failure payload (stdout under `--json`)

```json
{
  "error_code": "E_MATERIALIZE_UNSUPPORTED",
  "message": "audio codec 'opus' not supported in Sprint 5",
  "asset_id": "asset_hd_main",
  "field": "audio[0].codec",
  "supported": ["aac"],
  "materialization_report_path": "fixtures/run-001/materialization.json"
}
```

`materialization_report_path` is omitted whenever the row in the "writes materialization.json?" column above is "no" — that is, for every pre-synthesis failure (timeline rejection, matrix unsupported, capability gate, containment). It is present only for the synthesis-time failures (tool failure, probe parse error) where a run-dir has been allocated and a report has been written to disk.

The full `MaterializationReport` lives on disk; the stdout payload is the fast diagnostic for agents that don't want to re-read the file.

### Human-readable failure shape

```
chaos-librarian: materialize failed (E_MATERIALIZE_UNSUPPORTED)
  asset:     asset_hd_main
  field:     audio[0].codec
  message:   audio codec 'opus' not supported in Sprint 5
  supported: aac
  report:    fixtures/run-001/materialization.json
```

### Exception hierarchy

```python
class MaterializationError(Exception):
    error_code: str
    asset_id: str | None
    field: str | None
    payload: dict[str, object]

class TimelineUnsupportedError(MaterializationError): ...
class UnsupportedMaterializationError(MaterializationError): ...
class ToolFailedError(MaterializationError):
    invocation: ToolInvocation
class ProbeParseError(MaterializationError): ...
class ContainmentViolationError(MaterializationError): ...   # exit 7
class CapabilityGateError(MaterializationError): ...         # exit 4
```

A single `cli/app.py:materialize` try/except converts each subclass to the right exit code, JSON payload, and `materialization.json` write. No unstructured Python tracebacks leak under `--json`.

## Testing Strategy

Five test layers, mirroring source layout under `tests/`.

### Layer 1 — Contract drift gate (existing, extended)

`schema_export.py --check` runs in CI and is the lockstep guarantee for every contract change. Sprint 5 brings into the drift suite:

- `capabilities.schema.json` (new at v1)
- `manifest.schema.json` (regenerated at v2)
- `materialization.schema.json` (regenerated at v2)
- `replay-bundle.schema.json` (regenerated at v3)
- `scenario.schema.json` (regenerated at v2)
- `asset-report.schema.json` (regenerated at v2)
- `run-sentinel.schema.json` (regenerated at v2)

`tests/contract/test_contract_constants.py` gains an assertion for `CAPABILITIES_SCHEMA_VERSION`.

### Layer 2 — Pure unit tests (no subprocess, no I/O)

```
tests/materializer/test_recipes.py
  - one test per source: mandelbrot, color_bars, solid_color, sine, silence, channel_tones, generated_srt
  - asserts FFmpegInput.lavfi matches an inline expected value for a fixed (seed, params)
  - asserts SRT payload bytes match an inline expected value (catches line-ending drift)

tests/materializer/test_ffmpeg_builder.py
  - asserts build_command produces a stable argv for every cell in the Sprint 5 matrix:
      2 containers x 1 video codec x 3 resolutions x 1 audio codec x 3 channel layouts = 18 cases
  - asserts unsupported combos (webm, opus, 4k, etc.) raise UnsupportedMaterializationError with
    the exact field name in the payload
  - asserts every argv contains BITEXACT_FLAGS

tests/materializer/test_capabilities.py
  - subprocess.run monkeypatched at the module boundary
  - cases: all three tools at minimum, ffmpeg below minimum, mkvtoolnix missing (ready_for static
    is still True), all tools missing, malformed version output, subprocess timeout
  - one assertion per case on the resulting Capabilities model
  - version-normalization cases for _canonical_version_from_tool_output (Finding 4):
      * `ffmpeg version 7.1.1 Copyright (c) 2000-2024 ...`        -> ok
      * `ffmpeg version n7.1-0ubuntu1`                            -> ok (normalizes to 7.1)
      * `ffmpeg version 7.0.2-3ubuntu1`                           -> ok (normalizes to 7.0.2)
      * `ffmpeg version n7.0 Copyright ...`                       -> ok (normalizes to 7.0)
      * `ffmpeg version 6.1.1 Copyright ...`                      -> below minimum
      * `ffmpeg version N-118412-g0ce1c8f7c5 (git build)`         -> malformed-output, meets_minimum=false
      * `ffmpeg version <garbage>`                                -> malformed-output, meets_minimum=false
```

### Layer 3 — Materializer orchestrator unit tests (mocked subprocess)

```
tests/materializer/test_run.py
  - run_ffmpeg and probe_file patched at module boundary
  - asserts orchestrator: rejects non-empty timeline (E_MATERIALIZE_TIMELINE_UNSUPPORTED),
    rejects unsupported codec (E_MATERIALIZE_UNSUPPORTED), records ffmpeg failure correctly
    (E_MATERIALIZE_TOOL_FAILED with the failing invocation index), wipes library/ on failure,
    writes materialization.json with the expected outcome string in every error case
  - asserts the success path produces a manifest with content_hash and probed populated for
    every asset (using a stubbed probe_file returning a fixed ProbedMedia)
```

### Layer 4 — Real-tool integration tests (skip-if-not-installed)

```
tests/integration/test_materialize_real.py
  pytest.mark.skipif(not _ffmpeg_meets_minimum(), reason="ffmpeg >= 7.0 not available")

  - test_materialize_static_library_smoke:
      fixture with three assets covering mkv+h264+srt and mp4+aac+stereo;
      materialize, then assert every asset exists, ffprobe(file) returns parseable JSON,
      manifest content_hash matches sha256_hex(file_bytes), no entries in materialization.failures;
      asset.probed.streams[] contains only kind="video"/"audio" entries (no subtitle stream);
      for every sidecar in manifest.current.sidecars, the sidecar file exists at
      library/<path> and its sha256 matches sidecar.content_hash

  - test_materialize_bitexact_same_toolchain:
      materialize the same scenario twice into different out-dirs;
      assert manifest.current.json.assets[].content_hash matches across runs
      (same-toolchain determinism contract)

  - test_materialize_cross_mode_logical_oracle_ids:
      run plan on scenario S; run materialize on scenario S; same seed;
      assert journals are byte-identical (empty in Sprint 5);
      assert manifests are identical after canonicalize() strips {content_hash, probed}

  - test_materialize_unsupported_codec:
      hand-crafted scenario with audio codec opus;
      assert exit 5, stdout JSON error_code: E_MATERIALIZE_UNSUPPORTED,
      materialization_report_path is absent from stdout JSON, and
      <out-dir> does not exist on disk (lazy allocation guarantee)

  - test_materialize_tool_failure:
      monkeypatch ffmpeg binary path to a script that exits 1;
      assert exit 5, error_code E_MATERIALIZE_TOOL_FAILED, library/ wiped, sentinel intact
      (state="complete" because the failure was caught), materialization.json present

  - test_materialize_interrupted_recovery:
      synthesize a partial fixture (mock FFmpeg to write bytes then receive SIGTERM mid-run);
      assert sentinel exists with state="in_progress";
      run `chaos-librarian inspect <run-dir>`; assert it reports state="in_progress" and exits 0;
      run `chaos-librarian step <run-dir>`; assert it exits 7 with E_SENTINEL_IN_PROGRESS;
      run `chaos-librarian clean <run-dir>`; assert it succeeds and removes the dir

  - test_capabilities_real:
      run `chaos-librarian capabilities --json` as a subprocess;
      assert Capabilities.model_validate(stdout) round-trips;
      assert exit 0 on CI's ffmpeg; xfail with a clear marker if ffmpeg below minimum
```

Plus a sibling unit test for the canonicalization rule:

```
tests/contract/test_canonicalize.py
  - builds two synthetic manifests differing only in to-be-stripped fields
    (content_hash, probed, wall_clock_time, run_id, toolchain)
  - asserts canonicalize(left) == canonicalize(right)
  - asserts canonicalize preserves the structural fields (works/variants/bundles/assets ids,
    locations, sidecars)
```

The canonicalization helper itself ships in `chaos_librarian/contract/canonicalize.py` as a pure function over `Manifest`. Sprint 9's voom-v2 adapter will be its first cross-toolchain consumer; Sprint 5 only proves it doesn't strip too much.

### Layer 5 — CLI integration tests

```
tests/cli/test_capabilities.py
  - exit 0 + JSON payload when tools meet minimum (mocked detect_capabilities)
  - exit 4 + JSON payload when ffmpeg missing
  - human-output formatting smoke test

tests/cli/test_materialize.py
  - end-to-end via Typer CliRunner with detect_capabilities and materialize_scenario both mocked
  - asserts exit codes, --json payloads, materialization.json contents, library/ presence,
    sentinel presence; same shape as Sprint 4's cli/test_plan.py
```

### Existing-fixture validation

`tests/contract/test_sample_scenarios.py` re-runs after the scenario schema bump and confirms every fixture under `tests/fixtures/scenarios/` validates against `scenario.schema.json` v2 with the new defaulted `source` fields. Any pre-existing fixture that breaks blocks the PR.

### New scenario fixture

`tests/fixtures/scenarios/static-library.yaml` — a static library with three assets covering the Sprint 5 matrix (mkv+h264+aac, mp4+h264+aac+5.1, mkv+h264+srt sidecar). Used by the static-materialize smoke test and as a contract corpus entry.

### Out of scope for Sprint 5 tests

- Materialize replay round-trip (replay is plan-only-only this sprint).
- Cross-toolchain hash comparison (no second toolchain in CI yet).
- Performance benchmarks (Sprint 5 stays under the 50 MB cap; full perf budget is Sprint 10).
- Mutation paths (Sprint 6/7).

## Exit Criteria

From the source design doc:

- ✅ Materialized files probe successfully with ffprobe → Layer 4 `test_materialize_static_library_smoke`.
- ✅ Manifest includes content hashes and probed media facts → Layer 4 smoke test asserts both fields are present and consistent with the file bytes.
- ✅ Plan-only and materialized runs share the same logical oracle IDs → Layer 4 `test_materialize_cross_mode_logical_oracle_ids`.

Plus the additions resolved during brainstorming:

- `chaos-librarian capabilities --json` returns valid `Capabilities` JSON and the right exit code.
- `chaos-librarian materialize` rejects non-empty timelines with the right error code.
- Same-toolchain materialize is byte-deterministic (asserted by `test_materialize_bitexact_same_toolchain`).
- All seven schema artifacts in the drift gate validate after `--write` (capabilities new at v1; manifest, materialization, replay-bundle, scenario, asset-report, and run-sentinel regenerated at their bumped versions).

## Alternatives Rejected

- **Continue-past-failures.** Asset 17 fails; continue with assets 18..30, record per-asset success/failure. Rejected because the resulting on-disk library is a deliberate lie — the manifest says 30 assets, only 23 exist — and Rule 12 ("Fail loud") prefers a clean abort.
- **Two-pass dry-run-then-commit.** Synthesize every asset to /tmp, hash, then move into place. Eliminates partial-failure ambiguity but doubles materialization time for zero Sprint-5 gain (no concurrent reader needs the protection yet).
- **Manifest v2 with required hash/probed fields.** Forces plan-only to emit sentinel hashes. Rejected because it contradicts the "plan-only is real, materialize is augmented" framing.
- **Sidecar `manifest.probed.json`.** Keeps manifest at v1 but splits the contract into two files. Rejected because adapter authors then load two files for one logical concept.
- **Ship materialize replay this sprint.** Implements the canonicalizer end-to-end. Rejected because the canonicalizer has nothing meaty to compare against until Sprint 6/7 mutations land; designing it now risks reworking when real mutation data forces edge cases.
- **Approach B (everything in `engine/`)** and **Approach C (capabilities standalone + materializer package).** Rejected in favor of Approach A — keeping the engine pure plan-only and putting subprocess concerns in a sibling package.

## Adversarial Review Log

The Codex adversarial review of this spec (2026-05-18) returned a `needs-attention` verdict with four findings. Each is resolved by the edits in this revision; the spec now reflects those resolutions.

- **Finding 1 (HIGH) — Sidecar subtitle probing.** The original spec implied that SRT sidecar facts would surface in `asset.probed.streams[]`, but `ffprobe(asset_path)` cannot see standalone `.srt` files, so any implementation would either lie or silently drop them. Resolution: `ManifestSidecar` gains `content_hash: str | None = None` (Decision 5); the materializer hashes each sidecar's bytes and records `sha256:<hex>` there. Sprint 5 explicitly does not run ffprobe on sidecars and does not add subtitle streams to `asset.probed`; embedded subtitles arrive in Sprint 7. The Layer 4 smoke test now asserts sidecar existence and hash agreement instead of subtitle streams on the asset.
- **Finding 2 (HIGH) — Crash leaves "trusted" partial run-dir.** The original sentinel was written at the start of synthesis with no marker distinguishing in-progress from complete state. A signal between sentinel write and metadata write would leave a "trusted" partial directory with no metadata. Resolution: `RunSentinel` gains `state: Literal['in_progress', 'complete'] = 'complete'` (Decision 13); `RUN_SENTINEL_SCHEMA_VERSION` bumps 1 → 2. Materialize writes `state: 'in_progress'` first and flips to `state: 'complete'` in the final atomic batch (or on caught-failure cleanup); only uncaught crashes leave `in_progress`. `inspect` reports the state; `step` refuses `in_progress` with `E_SENTINEL_IN_PROGRESS` (exit 7); `clean` accepts both. New Layer 4 `test_materialize_interrupted_recovery` exercises the full crash-detect-clean loop.
- **Finding 3 (MEDIUM) — Unsupported-matrix contradiction.** Three places in the spec disagreed on whether `E_MATERIALIZE_UNSUPPORTED` produces a `materialization.json`. Resolution: the lazy-allocation contract wins — pre-synthesis failures write nothing on disk. The Exit-5 outcome mapping table now carries an explicit "writes materialization.json?" column making the rule machine-checkable; the JSON failure payload note points back to the same column; the Layer 4 `test_materialize_unsupported_codec` asserts the run-dir does not exist on disk.
- **Finding 4 (MEDIUM) — Distro-tagged FFmpeg version strings.** Passing strings like `n7.1-0ubuntu1` directly into `packaging.version.Version(...)` raises `InvalidVersion`, which the original spec said to treat as "malformed-output not-found" — meaning a working Ubuntu-packaged FFmpeg would fail the gate. Resolution: a normalization helper `_canonical_version_from_tool_output(raw)` strips a leading `n`/`N` and any trailing distro suffix, retaining only the `MAJOR[.MINOR[.PATCH]]` triplet before constructing a `Version`. Git-snapshot builds (`N-118412-g0ce1c8f7c5`) still return `None`. The Layer 2 case list pins the seven accepted/rejected input forms.

## Open Questions

None. All design decisions were resolved during brainstorming and the four findings above are closed.
