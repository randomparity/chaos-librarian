# Run Visualizer — Design

**Date:** 2026-06-11
**Status:** Approved
**Deliverable:** `scripts/visualize_run.py` + `scripts/visualize_template.html` — a post-hoc
exporter that turns one scenario run directory into a single self-contained HTML file for
scrubbing the library's state forwards and backwards through the run's timeline.

## Problem

While iterating on chaos-librarian scenarios it is hard to see what the synthetic library
looks like at a given point in a run, or how an individual file evolved across the run.
The journal is authoritative but is a flat JSONL stream; the manifest only shows final
state. There is no way to "scroll through time."

## Requirements

- Scroll forwards/backwards through a run's timeline and see the library contents at each step.
- Click a file at any step to see its layout at that moment (container, tracks, languages,
  hash, variant/bundle context, sidecars).
- From a selected file, view its entire change timeline; jumping between the two views is
  one click.
- Post-hoc workflow: open the artifact after (or mid-) run; no live tailing.
- Self-contained output: double-click to open, no server, archivable per run.

## Decisions (settled during brainstorming)

| Decision | Choice |
|---|---|
| Live vs post-hoc | Post-hoc |
| Data delivery | Exporter embeds JSON in one self-contained HTML file |
| Integration point | `scripts/` tool (no CLI-contract commitment; may graduate later) |
| State computation | Engine replay in Python; viewer JS is render-only |
| Main layout | Hybrid: state-first file tree + colored per-event strip/scrubber |
| File detail | Right-side drawer with Layout / Timeline tabs |
| Probed media | Model state at every step, plus a static "probed (final)" section when available |

## Architecture

```
run-dir (scenario.yaml, replay.json, journal.jsonl, manifest.initial.json)
        │
        ▼
scripts/visualize_run.py          ← engine replay, snapshot per event
  build_initial_state() ──► apply_event() × N ──► to_manifest() after each
        │
        ├── snapshots[0..N]   manifest JSON per step (step 0 = seeded initial state)
        ├── events[1..N]      journal entries, verbatim
        ├── diffs[1..N]       added/removed/changed entity ids + paths, computed in Python
        │
        ▼
out.html = visualize_template.html + one <script type="application/json"> payload island
```

- **Input:** one scenario run dir (e.g. `chaos-test-out/.../materialize-active-library-churn/`).
  Multi-scenario parents (`functional-*`) are out of scope.
- **Output:** `<run-dir>/visualize.html` by default; `-o/--output` overrides.
- The exporter re-resolves the scenario timeline through the same engine path that
  `plan`/`replay` use, seeded from `replay.json`, so rendered state is exactly what the
  oracle asserts. The on-disk journal is cross-checked against replayed entries by
  `event_id` sequence; any mismatch is a hard error.
- The viewer contains **zero event semantics**: no JS reducer, no duplicated handler logic.
  New engine actions render correctly with no viewer change (they arrive as snapshots/diffs;
  only the category color map may want a new entry, with a neutral fallback color otherwise).
- Vanilla JS + inline CSS, no external dependencies, must work from `file://`.

## Main screen

- **Header bar:** scenario id, run id, execution mode, step `t / N`, current event's
  action + event_id.
- **Canvas — library tree at step t:** directories → files from `snapshots[t].locations`
  + `sidecars`. In-flight multi-phase temp paths (`location.temp_path`) render ghosted with
  `bytes_written` progress. Files touched at step t are highlighted in the event-category
  color; adds/removes are visually distinct. Badges: ⚠ for versions with a `corruption`
  record, "stale" for stale podcast episodes.
- **Event strip + scrubber:** one tick per journal entry, colored by action category:
  content (reencode/remux/edit-metadata/corrupt-tags), path (move/rename/archive/
  move-between-roots), sidecar/subtitle, multi-phase lifecycle (start/progress/commit/abort),
  corruption, fs-chaos (lag/lock/permissions/quota/readonly/stale-handle/unmount/remount/
  touch-mtime), hierarchy (renumber/swap/move-episode/rename-season/republish/mark-stale),
  negative-oracle (wrong-oracle-hash). Click or drag sets the playhead; `←`/`→` step by one
  event; `Home`/`End` jump to extremes. Hover tooltip: event_id, action, target_ids.
- Events with no file effect still occupy a tick. Hierarchy events (renumber/swap/
  move-episode/rename-season) highlight the affected subtree in the canvas; environment
  events with no path target (lock/lag/quota windows) show a transient banner under the
  header bar instead.

## File detail drawer

Click a file → right drawer slides in; tree and scrubber stay live. Selection identity is
the **asset id** (or sidecar id), not the path, so the drawer follows the file across
renames/moves while scrubbing.

- **Tab 1 — Layout @ step t:** path; role; container; duration; variant label, bundle id,
  parent work context (movie title / series–episode / artist–album–track); version index +
  content hash; track table (video / audio / subtitle rows with codec, **language**,
  default/forced flags) from the engine's model state at step t; sidecars attached to the
  asset; corruption record if present. When the run dir's `manifest.current.json` carries
  ffprobe data (materialize/run modes), a static **"probed (final)"** section shows
  container, streams, and languages as ffprobe saw them at run end, for comparison against
  model truth. Plan-only runs have no probed data by design; the section is omitted.
- **Tab 2 — Timeline (N events):** every journal event whose `target_ids`/`location_ids`
  reference the asset, as a vertical list: action, phase, logical time, human-readable
  delta (`from_path → to_path`, hash change, track add/remove derived from per-step diffs).
  The playhead's row is highlighted; clicking any row jumps the global playhead to that step.

## Error handling

- Missing `scenario.yaml` / `replay.json` / `journal.jsonl` → fail fast, naming the missing
  artifact and the command that produces it.
- Journal divergence from replay (tampered/truncated) → hard error citing the first
  mismatched event_id. Never render silently-wrong state.
- Empty timeline → render step 0 (seeded library) with an empty strip.
- Payload size: full snapshot per step, no keyframe/delta encoding (YAGNI at current
  scales, ~KBs per step). If serialized payload exceeds 50 MB the exporter warns; slicing
  options are a future addition, not built now.

## Testing

- `tests/scripts/test_visualize_run.py`:
  - snapshot count == event count + 1;
  - diff correctness on a fixture scenario covering move, slow-copy (in-flight temp state),
    and embed-subtitle (track-level change);
  - journal-mismatch → hard error;
  - missing-artifact → actionable error.
- Payload contract test: embedded JSON island parses; every diff references entity ids
  present in its adjacent snapshots (behavior, not implementation).
- Viewer smoke test: generate HTML for a fixture run, assert the JSON island is present and
  parseable. Interactive behavior is verified manually in a browser; no JS test harness
  dependency in v1.

## Non-goals

- Live tailing of an in-progress run (re-export to refresh).
- Multi-run / cross-run comparison views.
- Divergence visualization against consumer observed-state (possible follow-up).
- Per-step probed data (ffprobe runs once at run end; per-step media truth is the model).
- CLI-contract `visualize` command (graduation path if the script proves out).
