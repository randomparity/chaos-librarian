# Issue #181 — Authorable Sidecar Encoding and Body Content

> Status: Draft · Sprint: issue-181 · Schema impact: SCENARIO_SCHEMA_VERSION 23 → 24

## Problem

Three sidecar chaos recipes surfaced by the recipe library (#108) are
inexpressible because the `create_sidecar` timeline event carries no authorable
byte-encoding, body content, or media-type knob:

- `sidecar/wrong-encoding` — a subtitle sidecar written in a non-UTF-8 encoding.
- `sidecar/nfo-xml-injection` — an NFO sidecar whose body the author controls.
- `sidecar/poster-is-video` — a "poster" whose bytes are a video, not an image.

Today `create_sidecar` always synthesizes a UTF-8 SRT (subtitle), a fixed-template
NFO, or a PNG poster. The author cannot deviate. The declared-subtitle path
(`asset.subtitles[*]`) already exposes `codec` / `source` / `encoding` and rejects
unsynthesizable combos (e.g. `ass` + `utf16_le`) via `E_MATERIALIZE_UNSUPPORTED`
in `rule_materialize_media_matrix`, but the *timeline* `create_sidecar` event has
none of that surface, so those three recipes were dropped from #108 (see that
spec's "Dropped proposals").

## Goals

- Add authorable content knobs to the `create_sidecar` timeline event so all three
  recipes become *genuinely valid* scenarios (`chaos-librarian validate` exits 0).
- Make the deferred `ass` + `utf16_le` rejection a **live, testable contract on the
  timeline event**, raising the same `E_MATERIALIZE_UNSUPPORTED` an author gets from
  the declared-subtitle path.
- Materialize each knob to the exact bytes the author requested (encoding-correct
  subtitle bytes, the author's NFO body verbatim, video bytes at a poster path).
- Preserve backward compatibility: every existing `create_sidecar` scenario (and the
  shipped recipes) stays valid, and when the new fields are omitted the materializer
  executes the *identical pre-change code path* (same `.encode("utf-8")`, same
  `render_nfo`, same `poster_ffmpeg_argv` argv) — a no-op refactor, not a frozen-hash
  promise.

## Non-goals

- Reworking the declared-subtitle (`asset.subtitles[*]`) path — it already has these
  knobs; this change only brings the timeline event to parity for subtitle encoding.
- A general "arbitrary bytes at arbitrary path" primitive. The new knobs are scoped
  to the three named chaos shapes (encoding, NFO body, poster media-type).
- Authoring sidecar body content for subtitles or posters (body is NFO-only) or an
  `encoding` for NFO/poster (encoding is subtitle-only). Cross-kind misuse is rejected.
- File-reference or external-payload body sources (body is an inline string only).

## Ground truth: the current sidecar model

Verified against `contract/scenario.py`, `engine/events.py`,
`materializer/phase_b/media.py`, `materializer/phase_b/sidecar_bytes.py`, and
`validation/rules/materialize_media_matrix.py` on `main` (post-#112).

`CreateSidecarEvent` today:

```python
class CreateSidecarEvent(_TimelineEventBase):
    action: Literal[...CREATE_SIDECAR] = ...
    target: str
    to: str
    language: str | None = None          # subtitle requires; poster/nfo forbid
    kind: SidecarKind = SidecarKind.SUBTITLE
    # model_validator: (subtitle ⇒ language set) / (poster|nfo ⇒ language None)
```

Materialization (`_apply_create_sidecar`):

- `subtitle` → `srt_payload(...).encode("utf-8")` (always UTF-8).
- `nfo` → `render_nfo(sidecar_id=...)` (fixed template; sidecar_id is the only
  variable).
- `poster` → `poster_ffmpeg_argv(...)` (always a 400x600 PNG).

`update_sidecar` regenerates bytes from the live sidecar's `(kind, language)` via
`regenerate_sidecar`. The `LiveSidecar` dataclass and `ManifestSidecar` row carry
`(kind, language)` only.

The engine's `create_sidecar` `state_delta` carries `{sidecar_path, sidecar_id,
language, kind}`, enforced exactly by `_STATE_DELTA_KEYS` and
`test_state_delta_keys_match_contract`.

The declared-subtitle materialize matrix (the model for the new failure contract):

```python
_SRT_SUBTITLE_ENCODINGS = {"utf8", "utf8_bom", "utf16_le", "iso_8859_1"}
_ASS_SUBTITLE_ENCODINGS = {"utf8", "utf8_bom"}
_SUBTITLE_RECIPE_MATRIX = {
    ("srt", "generated_srt"): _SRT_SUBTITLE_ENCODINGS,
    ("ass", "styled_ass"):   _ASS_SUBTITLE_ENCODINGS,
    ("ssa", "styled_ass"):   _ASS_SUBTITLE_ENCODINGS,
}
```

## Design

### New fields on `CreateSidecarEvent`

Flat optional fields on the single event class (no discriminated sub-union). A
`model_validator` forbids cross-kind misuse (matching the `extra="forbid"` ethos).

| field | type | applies to kind | default | meaning |
| --- | --- | --- | --- | --- |
| `codec` | `SubtitleCodec \| None` | subtitle | `None` ⇒ `srt` | subtitle sidecar codec/format |
| `source` | `SubtitleSource \| None` | subtitle | `None` ⇒ `generated_srt` | subtitle synthesis recipe |
| `encoding` | `SubtitleEncoding \| None` | subtitle | `None` ⇒ `utf8` | subtitle byte encoding |
| `body` | `str \| None` | nfo | `None` ⇒ template | exact NFO bytes (UTF-8) |
| `media_type` | `SidecarMediaType \| None` | poster | `None` ⇒ `image` | poster synthesized media kind |

`SidecarMediaType` is a new `StrEnum`:

```python
class SidecarMediaType(enum.StrEnum):
    IMAGE = "image"   # current PNG poster
    VIDEO = "video"   # tiny video written at the poster path — the chaos
```

Rationale for each shape (full rejected-alternatives in
[ADR 0003](../../adr/0003-authorable-sidecar-content.md)):

- **Subtitle = full `codec`+`source`+`encoding` trio** (not encoding-only): the
  issue's purpose is making the deferred `ass`+`utf16_le` rejection a live timeline
  contract. Encoding-only could never exercise it (all four encodings are valid for
  SRT). The trio mirrors `SubtitleTrack` exactly.
- **NFO body = inline string** (not file-reference or payload enum): the codebase
  ships self-contained, deterministic, reviewable scenario YAML (ADR 0002). A
  file-reference adds a second artifact and a path-containment surface; an enum can't
  express arbitrary injection payloads the recipe name implies.
- **Poster `media_type` = closed `StrEnum` `{image, video}`** (not free string or
  boolean): matches the pervasive "only values materialize can synthesize, validated
  by a closed set" convention. A free string admits unsynthesizable values; a boolean
  can't grow to other mismatch kinds.

### Defaults and backward compatibility

All five fields default to `None`, and a `None` field selects the exact current
behavior:

- `codec=None, source=None, encoding=None` ⇒ `srt` / `generated_srt` / `utf8` (the
  current implicit subtitle recipe). A pre-existing subtitle `create_sidecar` with no
  new fields produces **byte-identical** output.
- `body=None` ⇒ `render_nfo(sidecar_id=...)` template (current NFO).
- `media_type=None` ⇒ PNG poster (current poster).

The materializer resolves `None` to the concrete default at the point of use, so the
"omitted field" and "field set to the default value" cases produce identical bytes.

**How "byte-identical" is actually verified.** Poster bytes come from ffmpeg lavfi
(version-dependent) and subtitle bytes from `srt_payload(..., seed=resolved_seed)`, so
a committed golden hash would flap on an ffmpeg upgrade. The backward-compat test does
*not* assert against a frozen hash. Instead it asserts the `None` branch is a no-op
refactor: for the SRT case, `_apply_create_sidecar` with `encoding=None` must call
`.encode("utf-8")` and produce bytes equal to the unchanged `srt_payload(...)
.encode("utf-8")`; for NFO, `body=None` must produce bytes equal to a direct
`render_nfo(sidecar_id=...)`; for poster, `media_type=None` must build the exact argv
`poster_ffmpeg_argv(...)` returns. These are equalities between the new code's `None`
branch and a direct call to the unchanged generator — no ffmpeg version dependence.

### Cross-kind exclusivity (`model_validator`, `E_FIELD_*`)

The existing `_check_language_matches_kind` validator is extended (renamed to
`_check_fields_match_kind`) to forbid:

- `codec` / `source` / `encoding` set when `kind != subtitle`.
- `body` set when `kind != nfo`.
- `media_type` set when `kind != poster`.

Plus the existing language/kind rules (subtitle requires `language`; poster/nfo
forbid it). Each violation raises a `ValueError` in the model validator, surfaced as
`E_FIELD_LITERAL`/`E_FIELD_*` exactly as the current language/kind check is. This is a
*shape* error (a field on the wrong kind), distinct from a synthesis-capability limit.

### Invalid-combo failure contract (`E_MATERIALIZE_UNSUPPORTED`, semantic rule)

A new semantic rule `rule_create_sidecar_content` (file
`validation/rules/create_sidecar_content.py`, registered in `semantic._RULES`)
rejects authored combos the materializer cannot synthesize, raising
`E_MATERIALIZE_UNSUPPORTED` — the same code the declared-subtitle path raises. It
checks, for each `create_sidecar` timeline event of subtitle kind:

- `(codec, source)` (defaulting `None` → `srt`/`generated_srt`) must be a key in the
  **timeline** recipe matrix, and `encoding` must be in that key's allowed set.

Because v1 only synthesizes the SRT recipe for the timeline event (see "Subtitle codec
scope"), the timeline matrix is **SRT-only** — it is *not* a verbatim reuse of the
declared path's `_SUBTITLE_RECIPE_MATRIX` (which also accepts `ass`/`ssa`):

```python
_CREATE_SIDECAR_SUBTITLE_MATRIX = {
    ("srt", "generated_srt"): _SRT_SUBTITLE_ENCODINGS,  # the lifted-shared set
}
```

The shared piece lifted to a common location is the **encoding set**
`_SRT_SUBTITLE_ENCODINGS` (`{utf8, utf8_bom, utf16_le, iso_8859_1}`), imported by both
the declared-path matrix and this timeline matrix. Consequences of the SRT-only matrix:

- `ass`/`ssa` codec (any encoding, including the otherwise-valid `utf8`) ⇒ unknown key
  ⇒ `E_MATERIALIZE_UNSUPPORTED` at `$.timeline[i].codec`. This is consistent with
  "Subtitle codec scope": no ASS synthesis in v1.
- `srt` + `utf16_le`/`iso_8859_1` ⇒ accepted (the `wrong-encoding` recipe).
- `srt` + an out-of-set encoding (none exist today, but future-proof) ⇒
  `E_MATERIALIZE_UNSUPPORTED` at `$.timeline[i].encoding`.

The deferred `ass`+`utf16_le` rejection is therefore satisfied a fortiori: ASS is
rejected for *every* encoding, so `ass`+`utf16_le` raises `E_MATERIALIZE_UNSUPPORTED`
just like the declared path — the same code, even though the timeline rejects at the
`codec` loc (ASS-unsupported) rather than the `encoding` loc.

No materialize check is needed for NFO `body` (any non-empty UTF-8 string is writable)
or poster `media_type` (both enum values are synthesizable).

Why semantic-rule + `E_MATERIALIZE_UNSUPPORTED` rather than a model_validator: an
author who hits `ass`+`utf16_le` should get the **same** error whether they declared
it on `asset.subtitles[*]` or authored it via `create_sidecar`. A new code would
fragment the contract; a model_validator would misclassify a synthesis-capability
limit as a shape error.

### Materialization

`state_delta` for `create_sidecar` gains the five fields (added to `_STATE_DELTA_KEYS`,
so `test_state_delta_keys_match_contract` enforces them):
`{sidecar_path, sidecar_id, language, kind, codec, source, encoding, body, media_type}`.
Fields default to `None` in the delta when unset.

Handler routing in `_apply_create_sidecar`:

- **subtitle**: build the SRT body, then `.encode(<encoding>)` instead of the hardcoded
  `"utf-8"`. The encoding map (`utf8` → `"utf-8"`, `utf8_bom` → utf-8 with a BOM,
  `utf16_le` → `"utf-16-le"`, `iso_8859_1` → `"iso-8859-1"`) lives next to
  `srt_payload`. `codec`/`source` other than the SRT default are reserved for a later
  task (the validate matrix already allows only `(srt, generated_srt)` to reach an
  encoding other than utf8 paths the recipe needs); for v1 the handler synthesizes an
  SRT body for every subtitle and applies the requested encoding. `ass`/`ssa` codecs
  are *validatable* (the matrix accepts `(ass, styled_ass, utf8)`), but the timeline
  `wrong-encoding` recipe only needs `(srt, generated_srt, utf16_le)`. **Decision: the
  v1 materializer supports subtitle encoding for the SRT recipe and rejects non-SRT
  codecs at validate time** — see "Subtitle codec scope" below.
- **nfo**: if `body` is set, write `body.encode("utf-8")` verbatim; else
  `render_nfo(sidecar_id=...)`.
- **poster**: if `media_type == video`, emit a tiny deterministic video via ffmpeg
  lavfi (a few-frame `color`/`testsrc` muxed to a small container) at the poster path;
  else the current PNG.

#### `update_sidecar` on an authored sidecar

`update_sidecar` regenerates a sidecar's bytes via `regenerate_sidecar` using a
*perturbed* sub-seed (`perturbed_seed_for_update`, which folds in `event_id` so
consecutive updates produce distinct bytes — that is existing, intended behavior and is
preserved). The authored *content knobs* must survive that regeneration, so:

- `LiveSidecar` (an in-memory dataclass — widening it is **not** a schema change) gains
  `encoding`, `body`, and `media_type`, captured at create time and threaded into
  `regenerate_sidecar`.
- **Subtitle**: `regenerate_sidecar` regenerates the SRT body from the perturbed seed
  (so the body text changes per update, as today) but applies the **stored encoding**
  via the same encoding map — not a hardcoded UTF-8. An authored `utf16_le` subtitle
  stays UTF-16-LE across updates; only the cue text changes.
- **NFO**: the current `render_nfo` ignores the seed (template keyed on `sidecar_id`).
  When a `body` was authored, `update_sidecar` re-emits that **exact stored body**
  verbatim (the perturbed seed has no effect on an author-supplied body — there is no
  generator to perturb). When no body was authored, it re-emits the template, as today.
- **Poster**: `media_type` selects image-vs-video regeneration; the perturbed seed
  still varies the synthesized pixels/frames as today.

`ManifestSidecar` is unchanged on the wire (it does not and will not carry
encoding/body/media_type — those are synthesis inputs, not manifest identity), so
`MANIFEST_SCHEMA_VERSION` is not bumped.

A test updates an authored `utf16_le` subtitle and an authored-`body` NFO and asserts
the encoding (resp. the exact body) survives the update.

#### Subtitle codec scope (the one materialize-capability decision)

The `wrong-encoding` recipe needs `(srt, generated_srt, utf16_le)`. To keep the
materializer honest (no phantom capability), v1 supports **only the SRT subtitle
recipe** for timeline `create_sidecar`. The `_CREATE_SIDECAR_SUBTITLE_MATRIX` above therefore allows only
`(srt | None, generated_srt | None)` and rejects `ass`/`ssa` *codecs* on the timeline
event with `E_MATERIALIZE_UNSUPPORTED` (at the `codec` loc) — even though
`(ass, styled_ass, utf8)` is shape-valid — because `_apply_create_sidecar` does not
synthesize ASS bodies. This is recorded as a follow-up (timeline ASS sidecar synthesis)
per AGENTS.md Rule 13.

The deferred `ass`+`utf16_le` rejection is still satisfied and tested: an author who
writes `codec: ass, encoding: utf16_le` on `create_sidecar` gets
`E_MATERIALIZE_UNSUPPORTED`, the same *code* as the declared path (the timeline rejects
at the `codec` loc because ASS is unsupported in v1; the declared path rejects at the
`encoding` loc because ass+utf16 is an invalid combo — but both surface the identical
contract code).

### Schema version

`SCENARIO_SCHEMA_VERSION` 23 → 24 (adding fields to a contract model is breaking per
the project's no-minor-versions rule). `Scenario.schema_version` literal updated to
`Literal[24]`. The 146 files matching `schema_version: 23` under `tests/` and
`recipes/` are bumped to `schema_version: 24` as one mechanical step (the corpus tests
`test_sample_scenarios`, `test_invalid_corpus`, and `test_recipe_corpus` all enforce
the literal). **Exception:** `tests/fixtures/scenarios/invalid/yaml-parse-error.yaml`
pins `schema_version: 11` and expects `E_YAML_PARSE` — it never parses, so its version
is irrelevant and it is deliberately left untouched (it is not among the 146 and there
is no negative "wrong schema_version" fixture to preserve). The new invalid fixture
`create-sidecar-ass-utf16.yaml` ships at `schema_version: 24` with its
`# expected: E_MATERIALIZE_UNSUPPORTED` marker.

`MANIFEST_SCHEMA_VERSION` is **not** bumped — `ManifestSidecar` is unchanged.
`MATERIALIZATION_SCHEMA_VERSION` is **not** bumped — `MediaAction` is unchanged. Schema
artifacts regenerated with `--write` and committed.

## The three recipes

| Recipe | `create_sidecar` fields | Materializes to |
| --- | --- | --- |
| `sidecar/wrong-encoding.yaml` | `kind: subtitle, language: eng, encoding: utf16_le` | SRT bytes in UTF-16-LE |
| `sidecar/nfo-xml-injection.yaml` | `kind: nfo, body: "<movie>…injected…</movie>"` | the author's exact NFO bytes |
| `sidecar/poster-is-video.yaml` | `kind: poster, media_type: video` | a small video at a `.jpg`/poster path |

Each ships with the recipe header block (`# Recipe:` … `# Requires: none`) and is
discovered by `tests/recipes/test_recipe_corpus.py`, which already asserts every recipe
validates clean. These bring `recipes/sidecar/` from 3 to 6 recipes.

## Validation rules summary

| condition | layer | code |
| --- | --- | --- |
| `encoding`/`codec`/`source` on non-subtitle kind | model_validator | `E_FIELD_*` |
| `body` on non-nfo kind | model_validator | `E_FIELD_*` |
| `media_type` on non-poster kind | model_validator | `E_FIELD_*` |
| subtitle missing `language` / poster\|nfo with `language` | model_validator | `E_FIELD_*` |
| subtitle `(codec, source)` not in the SRT-only timeline matrix — any ASS/SSA codec (incl. `ass`+`utf16_le`) at `codec` loc; out-of-set `srt` encoding at `encoding` loc | semantic rule | `E_MATERIALIZE_UNSUPPORTED` |

## Failure modes and edge cases

- **Omitted new fields** → byte-identical to today (regression test asserts equal
  content_hash for a pre-change subtitle/nfo/poster `create_sidecar`).
- **`encoding: utf16_le` on a subtitle** → SRT bytes decode back as UTF-16-LE; the
  bytes differ from the UTF-8 form (test decodes and compares).
- **`encoding` on an NFO / `body` on a poster** → `E_FIELD_*` at validate time.
- **`codec: ass, encoding: utf16_le`** → `E_MATERIALIZE_UNSUPPORTED` (deferred
  rejection now live on the timeline event).
- **`body` an empty string** → an empty NFO file is written (zero-byte body is a legal,
  if degenerate, chaos input; no special-case rejection). *Open for spec review: do we
  forbid empty body?* — Decision: **forbid** empty body via `min_length=1` so an empty
  string is a clear authoring error rather than a silent zero-byte file, matching
  `EditMetadataEvent.fields` non-empty enforcement.
- **`update_sidecar` on an authored sidecar** → the cue text / pixels still vary by the
  perturbed seed (existing behavior), but the authored encoding survives, the authored
  NFO body is re-emitted verbatim, and the poster media_type is preserved (see
  "`update_sidecar` on an authored sidecar" above).
- **Schema bump** → every fixture/recipe `Literal[23]` mismatch fails the corpus tests
  until bumped to 24 (the intended forcing function).

## Acceptance criteria

- [ ] `create_sidecar` accepts `codec`/`source`/`encoding` (subtitle), `body` (nfo),
      `media_type` (poster); cross-kind misuse rejected at validate time (`E_FIELD_*`).
- [ ] any `ass`/`ssa` codec on `create_sidecar` (incl. `ass`+`utf16_le`) ⇒
      `E_MATERIALIZE_UNSUPPORTED`; `srt`+`utf16_le` is accepted.
- [ ] Subtitle sidecar materializes with the requested encoding; NFO with the requested
      body; poster as a video when `media_type: video`.
- [ ] Omitting the new fields produces byte-identical output to the pre-change behavior.
- [ ] Three new sidecar recipes ship and validate clean.
- [ ] `SCENARIO_SCHEMA_VERSION` bumped 23 → 24; schema artifact regenerated; all
      fixtures/recipes bumped.

## Testing

- Contract: `create_sidecar` accepts each new field for its kind; rejects each
  cross-kind misuse with `E_FIELD_*`; round-trips through `Scenario.model_validate`.
- Validation: a new invalid fixture `create-sidecar-ass-utf16.yaml`
  (`# expected: E_MATERIALIZE_UNSUPPORTED`); valid fixtures covering each new field.
- Materializer (env-gated ffmpeg where needed): subtitle encoding produces decodable
  UTF-16-LE bytes; NFO body written verbatim; poster video is a probe-valid video.
- Backward-compat (no ffmpeg needed): with the new fields `None`, the SRT branch's
  bytes equal `srt_payload(...).encode("utf-8")`, the NFO branch's bytes equal
  `render_nfo(sidecar_id=...)`, and the poster branch's argv equals
  `poster_ffmpeg_argv(...)` — code-path equality, not a frozen hash.
- `update_sidecar` of an authored `utf16_le` subtitle keeps UTF-16-LE bytes across the
  update; `update_sidecar` of an authored-`body` NFO re-emits the exact body.
- `test_state_delta_keys_match_contract` updated for the new `create_sidecar` keys.
- Recipe corpus: the three new recipes validate clean (existing
  `test_recipe_corpus.py`).
