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
run-dir (scenario.yaml, replay.json, journal.jsonl; optional: manifest.current.json)
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
  Multi-scenario parents (`functional-*`) are out of scope. Required artifacts:
  `scenario.yaml`, `replay.json`, `journal.jsonl`. Optional: `manifest.current.json`,
  read only for the probed-final drawer section — absent → section omitted;
  `manifest.initial.json` is not consumed (replay seeds from the scenario itself).
- **Output:** `<run-dir>/visualize.html` by default; `-o/--output` overrides.
- The exporter re-resolves the scenario timeline through the same engine path that
  `plan`/`replay` use, seeded from `replay.json`, so rendered state is exactly what the
  oracle asserts.
- **Journal cross-check contract:** the on-disk journal is compared positionally against
  the replayed entries on `(event_id, action, phase)` only — `wall_clock_time` and other
  mode-specific fields are ignored, since plan-mode replay omits them while run-mode
  journals carry them. Two outcomes are distinguished:
  - **Prefix (mid-run / step-mode dir):** the journal matches positions `0..k` of the
    replayed sequence with `k < N`. Valid — the scrubber renders steps `0..k` normally and
    shows steps `k+1..N` as ghosted "planned, not yet executed" ticks that cannot be
    scrubbed into. Re-export after more steps to extend the live range.
  - **Divergence:** any position `i` where the on-disk entry differs from the replayed
    entry on the compared fields → hard error citing `i` and both event_ids. Never render
    silently-wrong state.
- **Prerequisite to verify during implementation:** plan-path replay must be
  journal-equivalent (on the compared fields) for materialize/run bundles, whose
  `replay.json` is a different `execution_mode` variant carrying an `execution_trace`.
  The exporter tests must include a real materialize run-dir fixture exercising the
  cross-check end to end. If equivalence turns out not to hold, that is a blocking
  design revision (the comparison contract must be renegotiated per mode), not a
  runtime fallback — there is no way to build snapshots from journal entries alone.
- The viewer contains **zero event semantics**: no JS reducer, no duplicated handler logic.
  New engine actions render correctly with no viewer change (they arrive as snapshots/diffs;
  only the category color map may want a new entry, with a neutral fallback color otherwise).
- Vanilla JS + inline CSS, no external dependencies, must work from `file://`.
- **Escaping contract:** the payload contains hostile strings by design — corrupt-tag fuzz
  events, adversarial paths and titles are this tool's subject matter. The exporter
  serializes the JSON island with `<` escaped as `\u003c` (so no `</script>` in payload
  data can terminate the island), and the viewer renders every payload-derived string via
  `textContent`/text nodes — never `innerHTML` — so scenario-controlled markup is inert.

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
the **location id** (or sidecar id), not the path and not the asset id: an asset can own
several on-disk files at once (slow-copy yields the original and the copy under one asset),
and each must open its own drawer with its own path history. The drawer header shows the
owning asset id and follows the location across renames/moves while scrubbing. If the
selected location does not exist at the current step (not yet created, or deleted), the
drawer stays open with a ghosted header — "not present at step t" — and the Timeline tab
remains fully usable.

- **Tab 1 — Layout @ step t:** path; role; container; duration; variant label, bundle id,
  parent work context (movie title / series–episode / artist–album–track); version index +
  content hash; track table (video / audio / subtitle rows with codec, **language**,
  default/forced flags) from the engine's model state at step t; sidecars attached to the
  asset; corruption record if present. When the run dir's `manifest.current.json` carries
  ffprobe data (materialize/run modes), a static **"probed (final)"** section shows
  container, streams, and languages as ffprobe saw them at run end, for comparison against
  model truth. Plan-only runs have no probed data by design; the section is omitted.
  Probed data is matched to the drawer by asset id; probed entries whose asset id does not
  exist in the final replayed snapshot are dropped with an exporter warning (they indicate
  a manifest written by a different run, not a render-worthy state).
  For a selected **sidecar**, Tab 1 shows the sidecar's kind, language, content hash, and
  path, plus the owning asset (linked — clicking it opens that asset's primary location
  drawer); the asset-only sections (track table, variant/bundle context, probed-final)
  are omitted.
- **Tab 2 — Timeline:** derived from the **per-step diffs**, not from a journal
  `target_ids` filter: every step whose diff touches the selected location, its owning
  asset, or that asset's versions/sidecars contributes a row, with the step's journal
  event attached as the cause. This captures indirect changes — a `rename_season` or
  `renumber_episode` that re-renders the file's path appears in the file's history even
  though its journal entry targets a hierarchy entity, not the asset. For a selected
  **sidecar**, membership is the analogue: steps whose diff touches the sidecar row itself
  (create/update/remove, path or hash change) or re-renders its path via the owning
  asset's moves or hierarchy changes. Each row: action, phase, logical time,
  human-readable delta (`from_path → to_path`, hash change, track add/remove). The
  playhead's row is highlighted; clicking any row jumps the global playhead to that step.

## Error handling

- Missing `scenario.yaml` / `replay.json` / `journal.jsonl` → fail fast, naming the missing
  artifact and the command that produces it. (`manifest.current.json` is optional — see
  Architecture; its absence is not an error.)
- Journal divergence from replay (tampered or edited) → hard error citing the first
  mismatched position and both event_ids. Never render silently-wrong state. A journal
  that is a verbatim **prefix** is not divergence — see the cross-check contract above.
- Malformed JSONL: a **final** line that fails to parse is a torn write — exactly what a
  crashed or still-running chaos run leaves behind. The preceding valid entries form the
  prefix; the exporter prints a warning and the viewer header shows a "journal ended
  mid-write" badge at the live/planned boundary. An unparseable **non-final** line is
  corruption, not tearing → hard error with the line number.
- Empty timeline → render step 0 (seeded library) with an empty strip.
- Payload size: full snapshot per step, no keyframe/delta encoding. The real scaling is
  **payload ≈ (events + 1) × serialized manifest size**, not a flat per-step cost: a
  hand-written scenario (≤50 events, ~5 KB manifest) is well under 1 MB, but a generated
  fuzz-lane run with hundreds of files (~100 KB manifest) and 1–2k events lands at
  100–200 MB. If the serialized payload exceeds 50 MB the exporter warns and names the
  scaling cause. The designated escape hatch — sharing unchanged entity lists by reference
  across steps — is recorded here but not built until a real run trips the warning.

## Testing

- `tests/scripts/test_visualize_run.py`:
  - snapshot count == event count + 1;
  - diff correctness on a fixture scenario covering move, slow-copy (in-flight temp state),
    embed-subtitle (track-level change), and a hierarchy event (`rename_season` or
    `renumber_episode`) whose indirect path re-render must appear in the affected
    location's timeline rows;
  - journal divergence → hard error citing position and both event_ids;
  - journal prefix (truncated mid-run/step-mode journal) → valid export with the
    live/planned boundary at the journal head;
  - torn final JSONL line → valid export with warning and "ended mid-write" badge;
    unparseable non-final line → hard error with line number;
  - a real **materialize** run-dir fixture passes the cross-check end to end
    (verifies the plan-path-replay equivalence prerequisite);
  - hostile-string fixture: a scenario with `</script>` and `<img onerror=...>` in a
    title/path exports to HTML whose JSON island still parses and contains no raw `<`
    (verifies the escaping contract);
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
