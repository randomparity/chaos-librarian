# Implementation Plan — Existing-Media Import Mode (issue #105)

**Goal.** `chaos-librarian import <input-dir>` scans a real media library, probes
each file with ffprobe, detects sidecars, and emits a self-contained scenario
bundle (`scenario.yaml` + content-addressed `media/`) whose materialization
reproduces the originals byte-for-byte.

**Architecture.** Import assets carry `import_source: {path}` pointing at a
scenario-bundled copy of the original; materialization copies those bytes into
the library (ADR 0012). A new `chaos_librarian/importer/` package does
scan → probe → topology → emit; a new `import` CLI command wraps it. Validation
gains one lexical rule; the media-matrix rule and one capability gate learn to
skip import assets; the phase-B subtitle sidecar writer learns to honor `body`.

**Stack.** Python 3.13, `uv`, Pydantic v2, Typer, ruamel.yaml, ruff, `ty`,
pytest. ffprobe ≥ 7.0 for real-tool tests only.

## Global Constraints (transcribed from the spec — binding on every task)

- `SCENARIO_SCHEMA_VERSION` becomes `33`; models hardcode
  `schema_version: Literal[33]` (never `Literal[SCENARIO_SCHEMA_VERSION]` —
  `ty` rejects indirect Literals). Bump is breaking; regenerate
  `schemas/` in the same change that touches any contract model.
- Every new/changed BaseModel: `model_config = ConfigDict(extra="forbid")`
  (plus `frozen=True` in the Scenario subtree). Enum classes are
  `class X(enum.StrEnum)`. Absolute imports only.
- Negative tests build a `dict` payload and call `Model.model_validate(payload)`
  — never keyword-constructed invalid models, never `# type: ignore`, no stale
  `# noqa`.
- Typer arguments: `Annotated[Path, typer.Argument(...)]` / `typer.Option(...)`.
- Validation rules are pure: signature `(raw: Mapping[str, object],
  line_index: LineIndex, collector: IssueCollector) -> None`; never touch the
  filesystem. `rule_import_source` is lexical-only.
- Exit codes (docs/contract/cli-reference.md): 0 success; 1 operational
  failure (`E_IMPORT_FAILED`); 2 usage (`validate_new_out_path` →
  `typer.BadParameter`); 3 scenario validation failed; 4 required external
  tool missing; 5 materialization failed.
- Skip-reason vocabulary (import report): `mode:duplicate`, `cap:max_works`,
  `cap:max_works_sample`, `cap:max_variants`, `cap:max_duration_s`,
  `topology:no_anchor`, `topology:duplicate_episode`, `sidecar_duplicate`,
  `orphaned_sidecar`, `unrecognized`, `probe_failed`.
- Guardrail suite (run before every commit):
  `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests && uv run pytest -q`
  plus `uv run python -m chaos_librarian.schema_export --check` whenever
  `schemas/` could drift. Integration job additionally runs
  `uv run pytest tests/integration -q` (needs ffmpeg + mkvtoolnix + ffprobe).
- Branch: `feat/existing-media-import-105`; base: `main`. One logical change
  per commit; conventional-commit subjects ≤ 72 chars.

---

## Task 1 — Contract: `ImportSource`, import-asset validators, subtitle `body`, v33

**Files:** `src/chaos_librarian/contract/scenario.py`,
`src/chaos_librarian/contract/__init__.py`, `schemas/scenario.schema.json`
(regenerated), `tests/contract/test_import_assets.py` (new), all
`tests/fixtures/scenarios/**` (mechanical version bump), plus any test
asserting the literal version (grep `schema_version.*32` / `Literal\[32\]`
under `tests/`).

**Fits:** foundation — every later task consumes these models.

### Steps

1. **Failing test first.** Create `tests/contract/test_import_assets.py`:

   ```python
   """Import-asset contract: ImportSource exclusivity, shape, subtitle body."""
   import pytest
   from pydantic import ValidationError
   from chaos_librarian.contract.scenario import Asset, CreateSidecarEvent, ImportSource


   def _import_asset_payload(**overrides):
       payload = {
           "id": "imp-abc",
           "role": "main",
           "container": "mkv",
           "duration_seconds": 12.5,
           "import_source": {"path": "media/abc.mkv"},
       }
       payload.update(overrides)
       return payload


   def test_import_source_roundtrip():
       asset = Asset.model_validate(_import_asset_payload())
       assert asset.import_source == ImportSource(path="media/abc.mkv")


   @pytest.mark.parametrize("field", ["video", "mp4_moov_placement",
                                      "matroska_muxing_profile",
                                      "embedded_chapters",
                                      "embedded_cover_art"])
   def test_import_asset_forbids_synthesis_knobs(field):
       value = {"video": {"source": "mandelbrot", "codec": "h264", "resolution": "sd"}}
       payload = _import_asset_payload(**{field: value[field]})
       with pytest.raises(ValidationError, match="import_source asset forbids"):
           Asset.model_validate(payload)


   def test_import_asset_forbids_tracks():
       payload = _import_asset_payload(
           audio=[{"codec": "aac", "channels": "stereo", "language": "en"}])
       with pytest.raises(ValidationError, match="import_source asset forbids"):
           Asset.model_validate(payload)


   def test_import_source_mutually_exclusive_with_links():
       payload = _import_asset_payload(same_content_as="other-asset")
       with pytest.raises(ValidationError, match="mutually exclusive"):
           Asset.model_validate(payload)


   def test_subtitle_sidecar_event_accepts_body():
       event = CreateSidecarEvent.model_validate({
           "id": "ev1", "at": "0s", "target": "imp-abc",
           "to": "Movie.en.srt", "language": "en", "kind": "subtitle",
           "codec": "srt", "body": "1\n00:00:00,000 --> 00:00:01,000\nhi\n",
       })
       assert event.body.startswith("1\n")


   def test_poster_sidecar_event_still_forbids_body():
       payload = {"id": "ev2", "at": "0s", "target": "imp-abc",
                  "to": "poster.png", "kind": "poster", "body": "x"}
       with pytest.raises(ValidationError):
           CreateSidecarEvent.model_validate(payload)
   ```

   Run `uv run pytest tests/contract/test_import_assets.py -q` — expect
   failures (`ImportSource` does not exist; validators reject nothing).

2. **Implement.** In `contract/scenario.py`:

   - Next to `SymlinkTarget` add:

     ```python
     class ImportSource(BaseModel):
         """Scenario-bundled original backing an imported asset (ADR 0012).

         ``path`` is relative to the scenario file's directory, with safe
         components only; validation enforces the shape lexically and the
         materializer re-resolves it against the real filesystem.
         """

         model_config = ConfigDict(extra="forbid", frozen=True)
         path: str
     ```

   - `Asset`: add field `import_source: ImportSource | None = None` after
     `symlink`; in `_check_content_dedup_fields` add
     `("import_source", self.import_source)` to the `selected_fields` tuple
     list; add a second validator:

     ```python
     @model_validator(mode="after")
     def _check_import_asset_shape(self) -> Asset:
         if self.import_source is None:
             return self
         forbidden = [
             name
             for name, value in (
                 ("video", self.video),
                 ("mp4_moov_placement", self.mp4_moov_placement),
                 ("matroska_muxing_profile", self.matroska_muxing_profile),
                 ("embedded_chapters", self.embedded_chapters),
                 ("embedded_cover_art", self.embedded_cover_art),
             )
             if value is not None
         ]
         if self.audio:
             forbidden.append("audio")
         if self.subtitles:
             forbidden.append("subtitles")
         if forbidden:
             raise ValueError(f"import_source asset forbids: {', '.join(forbidden)}")
         return self
     ```

   - `CreateSidecarEvent._check_fields_match_kind`: replace the body check
     `if self.kind not in {SidecarKind.NFO, SidecarKind.CUE} and self.body
     is not None:` with `if self.kind == SidecarKind.POSTER and self.body is
     not None:` (message unchanged: "body is only valid for nfo and cue
     sidecars" → update to `"body is only valid for subtitle, nfo and cue
     sidecars"`). Update the field comment above `body` (v33: body also
     serves subtitle for imported sidecar text).

3. **Bump the version.** `contract/__init__.py`: `SCENARIO_SCHEMA_VERSION:
   Final = 33`. `contract/scenario.py`: `Scenario.schema_version:
   Literal[33]`. Then mechanically update all 195 fixture files:
   `grep -rl 'schema_version: 32' tests/ | xargs sed -i '' 's/schema_version: 32/schema_version: 33/'`
   (BSD sed on macOS; verify count before/after with `grep -rl ... | wc -l`).
   Grep `tests/` for remaining hardcoded `32` near `schema_version` or
   `SCENARIO_SCHEMA_VERSION` assertions and update each.

4. **Regenerate schemas:** `uv run python -m chaos_librarian.schema_export
   --write`. `git diff schemas/` must show only the scenario schema gaining
   `ImportSource`/`import_source` and enum/comment changes.

5. **Verify:** `uv run pytest tests/contract -q` (expect all green),
   `uv run python -m chaos_librarian.schema_export --check` (exit 0),
   `uv run ty check src tests`, `uv run ruff check . && uv run ruff format .`.
   Commit: `feat(contract): import-source assets and subtitle sidecar body (v33)`.

**Acceptance:** new tests pass; full contract suite green; schema drift gate
green; `ty` clean.

---

## Task 2 — Validation: `rule_import_source`, matrix gating, body exemption

**Files:** `src/chaos_librarian/validation/codes.py`,
`src/chaos_librarian/validation/rules/media/import_source.py` (new),
`src/chaos_librarian/validation/rules/media/materialize_media_matrix.py`,
`src/chaos_librarian/validation/rules/sidecar/create_sidecar_content.py`,
`src/chaos_librarian/validation/semantic.py`,
`tests/validation/test_import_source.py` (new),
`tests/validation/rules/media/test_media_matrix_import.py` (new),
`tests/fixtures/scenarios/invalid/import-source-*.yaml` (new).

**Interfaces consumed:** `iter_asset_contexts`,
`iter_assets_with_loc` (from `validation.rules.hierarchy.walkers`),
`Reporter` / `_as_mapping` (from `validation.rules.core.raw_helpers`),
`is_safe_path_component` (from `contract.paths`), `IssueCollector.add`.

### Steps

1. **Failing tests first** — `tests/validation/test_import_source.py` builds
   minimal raw scenario dicts (a movie with one import asset) and calls
   `rule_import_source(raw, line_index, collector)` directly, asserting
   `E_IMPORT_SOURCE_INVALID` issues for: absolute path (`"/etc/passwd"`),
   empty string (`""`), dot-only (`"."`), `..` escape
   (`"media/../../x.mkv"`), separator in a component (`"a/b\n c".replace` —
   use `"bad\\slash.mkv"`), control character (`"bad\x01.mkv"`). A valid
   relative path produces no issue. Build `line_index` the way existing rule
   unit tests do (reuse the helper from
   `tests/validation/rules/conftest.py` if present; otherwise
   `parse_scenario_bytes` on a tiny YAML).

2. **Implement** `validation/rules/media/import_source.py`:

   ```python
   """Rule: import_source.path must lexically resolve inside the scenario dir.

   Validation rules never touch the filesystem, so containment is proven by
   shape alone: a relative, non-empty path whose every component passes
   ``is_safe_path_component`` (which rejects ``..``, separators, and control
   characters) can only resolve strictly under the scenario file's directory.
   Existence and symlink escapes are re-checked by the materializer.
   """

   from __future__ import annotations

   from collections.abc import Mapping
   from typing import TYPE_CHECKING

   from chaos_librarian.contract.paths import is_safe_path_component
   from chaos_librarian.validation.codes import E_IMPORT_SOURCE_INVALID
   from chaos_librarian.validation.rules.core.raw_helpers import Reporter, _as_mapping
   from chaos_librarian.validation.rules.hierarchy.walkers import iter_asset_contexts

   if TYPE_CHECKING:
       from chaos_librarian.validation.reporting import IssueCollector
       from chaos_librarian.validation.scenario_io import LineIndex

   __all__ = ["rule_import_source"]


   def rule_import_source(
       raw: Mapping[str, object],
       line_index: LineIndex,
       collector: IssueCollector,
   ) -> None:
       """Reject import_source paths that could escape the scenario bundle."""
       reporter = Reporter(collector=collector, line_index=line_index)
       for context in iter_asset_contexts(raw):
           source = _as_mapping(context.asset.get("import_source"))
           if source is None:
               continue
           path_value = source.get("path")
           if not isinstance(path_value, str):
               continue  # Pydantic owns the type check
           _check_shape(path_value, (*context.asset_loc, "import_source", "path"), reporter)


   def _check_shape(path_value: str, loc: tuple, reporter: Reporter) -> None:
       if not path_value or PurePosixPath(path_value).is_absolute() or path_value.startswith(("/", "\\")):
           reporter.error(code=E_IMPORT_SOURCE_INVALID,
                          message="import_source.path must be relative and non-empty",
                          loc=loc)
           return
       parts = PurePosixPath(path_value).parts
       if ".." in parts:
           reporter.error(code=E_IMPORT_SOURCE_INVALID,
                          message="import_source.path must not contain '..'",
                          loc=loc)
           return
       for part in parts:
           if not is_safe_path_component(part):
               reporter.error(code=E_IMPORT_SOURCE_INVALID,
                              message=f"import_source.path has unsafe component {part!r}",
                              loc=loc)
               return
4. **Matrix gating** in `rule_materialize_media_matrix`:

   - In `_check_asset_context`, first line:

     ```python
     if isinstance(context.asset.get("import_source"), Mapping):
         return  # import assets materialize as byte copies (ADR 0012)
     ```

     (skips must-declare-video and audio-cardinality checks).

   - In the rule function, after the asset walk, reject declared-track
     mutation events targeting import assets:

     ```python
     _TRACKED_MEDIA_ACTIONS: Final[frozenset[str]] = frozenset({
         TimelineActionName.REENCODE_VIDEO.value,
         TimelineActionName.REENCODE_AUDIO.value,
         TimelineActionName.REMUX_CONTAINER.value,
         TimelineActionName.EMBED_SUBTITLE.value,
         TimelineActionName.EXTRACT_SUBTITLE.value,
     })

     import_asset_ids = {
         asset.get("id")
         for asset, _loc in iter_assets_with_loc(raw)
         if isinstance(asset.get("import_source"), Mapping)
         and isinstance(asset.get("id"), str)
     }
     for index, event in _iter_timeline_events(raw):
         if event.get("action") not in _TRACKED_MEDIA_ACTIONS:
             continue
         target = event.get("target")
         if isinstance(target, str) and target in import_asset_ids:
             reporter.error(
                 code=E_MATERIALIZE_UNSUPPORTED,
                 message=(
                     f"timeline event {event.get('action')!r} targets import asset "
                     f"{target!r}; import assets materialize as byte copies and "
                     "declare no tracks"
                 ),
                 loc=("timeline", index, "target"),
             )
     ```


     (`_iter_timeline_events` is imported from
     `validation.rules.core.raw_helpers`, which also defines `Reporter`
     and yields `(index, event)` — no `enumerate`. Mirror the import in
     `create_sidecar_content.py`.)

5. **Body exemption** in `rule_create_sidecar_content`: inside the subtitle
   branch, before reading codec/source:

   ```python
   if event.get("body") is not None:
       continue  # authored/imported body is authoritative (ADR 0012, v33)
   ```

6. **Invalid-corpus fixtures** under `tests/fixtures/scenarios/invalid/`,
   each starting `# expected: E_IMPORT_SOURCE_INVALID` (or
   `E_MATERIALIZE_UNSUPPORTED` for the mutation-event one):
   `import-source-absolute.yaml`, `import-source-empty.yaml`,
   `import-source-escape.yaml`, `import-source-control-char.yaml`,
   `import-source-mutation-event.yaml`. Model each on
   `tests/fixtures/scenarios/invalid/path-escape.yaml` (minimal movie +
   import asset, `schema_version: 33`).

7. **Verify:** `uv run pytest tests/validation -q` green; full guardrails;
   commit: `feat(validation): import_source lexical rule and matrix gating`.

**Acceptance:** rule unit tests + corpus fixtures green; `rule_import_source`
registered; matrix rule skips import assets; subtitle body events validate.

---

## Task 3 — Capability gate skips import assets

**Files:** `src/chaos_librarian/materializer/preparation/capability_gates.py`,
`tests/materializer/preparation/test_capability_gates_import.py` (new).

1. **Failing test:** build a `Scenario` (or the smallest object
   `assert_capable_for_webm_video` accepts — it iterates `iter_assets`)
   containing one import asset with `container="webm"`; with
   `caps.ready_for.materialize_webm_video=False` the call must NOT raise.
   A non-import webm asset still raises (existing behavior — regression
   guard).
2. **Implement:** in `assert_capable_for_webm_video`, change the skip to
   `if asset.container != "webm" or asset.import_source is not None: continue`.
3. **Verify:** `uv run pytest tests/materializer -q`; commit:
   `fix(materializer): webm capability gate skips import assets`.

---

## Task 4 — Materializer: copy path, evidence, missing-bundle error, subtitle body

**Files:** `src/chaos_librarian/materializer/errors.py`,
`src/chaos_librarian/materializer/run.py`,
`src/chaos_librarian/materializer/content/synthesis.py`,
`src/chaos_librarian/materializer/content/source_capabilities.py`,
`src/chaos_librarian/materializer/phase_b/media/handler.py`,
`src/chaos_librarian/media_matrix.py` (one constant),
`tests/materializer/content/test_import_copy.py` (new),
`tests/materializer/phase_b/test_subtitle_body_sidecar.py` (new).

**Interfaces consumed:** `PhaseAInputs` (gains `scenario_dir: Path`),
`_copy_same_content_asset` as the structural template, `ContentSourceEvidence`
(all fields required: `asset_id`, `track_kind`, `recipe_digest`,
`cache_disposition`), `probe_file`, `MaterializeAssetResult`.

### Steps

1. **`media_matrix.py`** — add shared constant (materializer and importer
   both need it; media_matrix is the existing shared home):

   ```python
   IMPORT_VIDEO_CONTAINERS: Final[frozenset[str]] = frozenset({
       "mkv", "mp4", "webm", "avi", "mov", "ts", "m4v", "wmv", "mpg", "mpeg",
   })
   ```

2. **`errors.py`** — new subclass beside `SymlinkTargetMissingError`:

   ```python
   class ImportSourceMissingError(MaterializationError):
       """An import asset's scenario-bundled source file is missing or escapes."""

       error_code: str = "E_IMPORT_SOURCE_MISSING"
   ```

3. **Failing tests** — `tests/materializer/content/test_import_copy.py`:
   build a tiny Scenario with one import asset whose `import_source.path`
   points at a real temp file inside the scenario dir; call
   `materialize_assets_phase_a` with a hand-built `PhaseAInputs`
   (`scenario_dir=tmp_path`, minimal `artifacts`/`caps` — reuse existing
   phase-A test fixtures in `tests/materializer/content/` for how
   `PlanArtifacts`/`Capabilities` stubs are built). Assert:
   output file bytes equal source bytes; `probed.duration_seconds` equals
   ffprobe of source (real ffprobe — mark the module like neighboring
   real-tool tests or stub `probe_file` via monkeypatch, matching existing
   conventions in that directory); returned `content_sources[0]` has
   `provider="import-file"`, `track_kind=VIDEO`, `recipe_digest ==
   content_hash`, `cache_disposition=NOT_CACHEABLE`; invocation tool is
   `"import_copy"`. Second test: `import_source.path = "../escape.mkv"` →
   raises `ImportSourceMissingError` (or `ContainmentViolationError` — see
   implementation, assert the exact class you implement). Third: missing
   file → `ImportSourceMissingError` with `error_code ==
   "E_IMPORT_SOURCE_MISSING"`.

4. **Implement the copy path** in `synthesis.py`:

   - `PhaseAInputs` gains `scenario_dir: Path` (after `out_dir`).
   - `materialize/run.py` passes
     `scenario_dir=scenario_path.resolve().parent` when constructing
     `PhaseAInputs` (find the construction site in
     `materialize_scenario`; `scenario_path` is already a parameter there).
   - Dispatch in `materialize_assets_phase_a`, after the
     `same_content_as` branch:

     ```python
     elif asset.import_source is not None:
        asset_result = _copy_import_asset(
            asset=asset,
            out_dir=inputs.out_dir,
            rendered_relative_path=rendered_relative_path,
            scenario_dir=inputs.scenario_dir,
            invocation_index=invocation_index,
        )
     ```

   - New function (modeled on `_copy_same_content_asset`, same return
     contract):

     ```python
     def _resolve_bundle_path(scenario_dir: Path, rel: str) -> Path:
         """Resolve an import_source path against the real scenario dir.

         Re-checks the lexical contract on the live filesystem: the resolved
         path must stay strictly inside ``scenario_dir`` even through
         symlinks.
         """
         if not rel or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
             raise ImportSourceMissingError(
                 f"import_source path {rel!r} is not a safe relative path",
                 asset_id=None,
             )
         root = scenario_dir.resolve(strict=True)
         resolved = (root / rel).resolve(strict=False)
         if root not in resolved.parents:
             raise ImportSourceMissingError(
                 f"import_source path {rel!r} escapes the scenario directory",
                 asset_id=None,
             )
         if not resolved.is_file():
             raise ImportSourceMissingError(
                 f"import_source file not found: {rel!r} (scenario dir {scenario_dir})",
                 asset_id=None,
             )
         return resolved


     def _copy_import_asset(
         *,
         asset: Asset,
         out_dir: Path,
         rendered_relative_path: str,
         scenario_dir: Path,
         invocation_index: int,
     ) -> MaterializeAssetResult:
         """Copy the scenario-bundled original into the library (ADR 0012).

         The materialized bytes ARE the original bytes: no synthesis, no
         matrix. Evidence records the copy as provider ``import-file`` with
         the content digest as ``recipe_digest`` (it identifies the exact
         content the copy produced).
         """
         assert asset.import_source is not None
         source_path = _resolve_bundle_path(scenario_dir, asset.import_source.path)
         library_dir = out_dir / "library"
         output_path = library_dir / rendered_relative_path
         output_path.parent.mkdir(parents=True, exist_ok=True)
         started = time.monotonic_ns()
         shutil.copyfile(source_path, output_path)
         duration_ns = time.monotonic_ns() - started
         with output_path.open("rb") as fh:
             content_hash = "sha256:" + hashlib.file_digest(fh, "sha256").hexdigest()
         probed = probe_file(output_path)
         invocation = ToolInvocation(
             tool="import_copy",
             version="n/a",
             command=["copyfile", str(source_path), str(output_path.relative_to(out_dir))],
             exit_code=0,
             duration_ns=duration_ns,
         )
         track_kind = (
             ContentTrackKind.VIDEO
             if asset.container in IMPORT_VIDEO_CONTAINERS
             else ContentTrackKind.AUDIO
         )
         evidence = ContentSourceEvidence(
             asset_id=asset.id,
             track_kind=track_kind,
             source="import",
             provider="import-file",
             recipe_digest=content_hash,
             origin_uri=asset.import_source.path,
             content_hash=content_hash,
             cache_disposition=CacheDisposition.NOT_CACHEABLE,
         )
         materialized_asset = MaterializedAsset(
             asset_id=asset.id,
             location_path=str(output_path.relative_to(out_dir)),
             content_hash=content_hash,
             size_bytes=probed.size_bytes,
             duration_seconds=probed.duration_seconds,
             invocation_index=invocation_index,
             mp4_moov_placement=None,
         )
         return MaterializeAssetResult(
             invocation=invocation,
             materialized_asset=materialized_asset,
             probed=probed,
             sidecar_hashes={},
             content_sources=(evidence,),
             prelude_invocations=(),
         )
     ```

     (Check `MaterializedAsset` field defaults — if `mp4_moov_placement`
     defaults to None, omit it; match `_copy_same_content_asset`.)

5. **Subtitle body branch** in `_write_subtitle_sidecar`
   (`phase_b/media/handler.py`), immediately after the language check:

   ```python
   if request.body_text is not None:
       body = encode_subtitle_body(
           request.body_text,
           request.encoding.value if request.encoding is not None else None,
       )
       request.temp_output.write_bytes(body)
       return _CreateSidecarWriteResult(
           tool_invocation_index=None,
           live_sidecar=LiveSubtitleSidecar(
               asset_id=request.asset_id,
               language=request.language,
               encoding=request.encoding.value if request.encoding is not None else None,
           ),
       )
   ```

   Test: build a journal entry whose state_delta carries
   `kind="subtitle"`, `body="1\n00:00:00,000 --> ..."` (reuse an existing
   phase-B sidecar test's entry-construction helper), run
   `_apply_create_sidecar`, assert the file bytes equal the encoded body —
   NOT `srt_payload` output.

6. **Capabilities provider** in `source_capabilities.py`: append a second
   `ContentSourceProviderCapability(name="import-file", available=True,
   requires_network=False, requires_cache=False, required_tool=None,
   sources=("video:file_ref", "audio:file_ref"))` to the returned
   `ContentSourceCapabilities.providers`, mirroring the existing entry's
   construction. Update `tests/` asserting provider counts (grep
   `collect_content_source_capabilities`).

7. **Verify:** `uv run pytest tests/materializer -q`; guardrails; commit:
   `feat(materializer): copy-path materialization for import assets`.

**Acceptance:** copy path produces byte-identical files with recorded
evidence; escape/missing raise `E_IMPORT_SOURCE_MISSING`; subtitle body
events write body bytes; capabilities lists the new provider.

---

## Task 5 — Importer package

**Files:** `src/chaos_librarian/importer/__init__.py` (new),
`src/chaos_librarian/importer/scan.py` (new),
`src/chaos_librarian/importer/probe_input.py` (new),
`src/chaos_librarian/importer/topology.py` (new),
`src/chaos_librarian/importer/emit.py` (new),
`tests/importer/test_scan.py`, `tests/importer/test_topology.py`,
`tests/importer/test_emit.py` (new; stub prober — no ffprobe).

**Interfaces consumed:** `probe_file` (`materializer.tooling.probe`),
`IMPORT_VIDEO_CONTAINERS` (`media_matrix`), `Scenario`,
`prepare_run_input_from_bytes` + `run_validation` (re-validation gate),
`write_generated_scenario`-style atomic write pattern
(`generation.api`), `SCENARIO_SCHEMA_VERSION`.

### Data contracts (shared across the package)

```python
# scan.py
@dataclass(frozen=True, slots=True)
class ScannedFile:
    path: Path          # absolute, as found
    kind: str           # "video" | "audio" | "subtitle" | "nfo" | "poster"

VIDEO_EXTENSIONS: Final[frozenset[str]] = IMPORT_VIDEO_CONTAINERS  # {"mkv", ...}
AUDIO_EXTENSIONS: Final[frozenset[str]] = frozenset({"flac", "mp3", "m4a", "wav", "ogg", "opus"})
SUBTITLE_EXTENSIONS: Final[dict[str, SubtitleCodec]] = {
    ".srt": SubtitleCodec.SRT, ".ass": SubtitleCodec.ASS, ".ssa": SubtitleCodec.SSA,
}
POSTER_EXTENSIONS: Final[frozenset[str]] = frozenset({".jpg", ".jpeg", ".png", ".webp"})
POSTER_STEM_PREFIXES: Final[tuple[str, ...]] = ("poster", "folder", "cover")

def scan_directory(root: Path) -> tuple[list[ScannedFile], list[SkipRecord]]:
    """Sorted-path walk; hidden dirs and symlinked dirs are not entered.

    Every file is classified or recorded as skipped with reason
    ``unrecognized``. Extension matching is case-insensitive.
    """
```

```python
# probe_input.py
@dataclass(frozen=True, slots=True)
class ProbedInput:
    scanned: ScannedFile
    probed: ProbedMedia
    sha256: str          # bare hex; bundle name uses f"{sha256}.{container}"

def probe_inputs(files: list[ScannedFile]) -> tuple[list[ProbedInput], list[SkipRecord]]:
    """ffprobe each media-kind file; failures become ``probe_failed`` skips.

    Sidecar kinds are not probed here (text/image files).
    """
```

```python
# topology.py — output shape consumed by emit
@dataclass
class ImportedWork:          # movie | series | artist; kind-tagged payload dicts
    kind: str                # "movie" | "series" | "artist"
    id: str                  # slug (+ "-<n>" disambiguator, sorted order)
    payload: dict            # movies/series/artists entry
    asset_payloads: list[dict]   # bundle.assets entries (with import_source)
    sidecar_events: list[dict]   # create_sidecar timeline events

def build_topology(
    probed: list[ProbedInput], sidecars: list[ScannedFile],
) -> tuple[list[ImportedWork], list[SkipRecord]]:
    """Classify per the spec: Season NN (not at scan root) → episodes;
    SxxEyy parse failures and duplicate SxxEyy → topology:no_anchor /
    topology:duplicate_episode; <Artist>/<Album>[/Disc NN]/ → tracks;
    root-level or artist-level audio → topology:no_anchor; other videos →
    movies (same-dir multiples = variants); sidecars attach to the
    lexicographically first stem-matching video, dedup per
    (video, kind, language), later duplicates → sidecar_duplicate; a
    sidecar whose video was not imported → orphaned_sidecar. Entity ids:
    slug of directory name with -<n> disambiguators in sorted order."""
```

Implementation notes for `build_topology` (the only subtle logic):

- Season detection: `re.fullmatch(r"season[ _-]?(\d{1,2})", dir.name, re.I)`.
- Episode numbering: `re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", stem)`; title
  = stem with the SxxEyy token stripped and sanitized via the same
  `clean_display_component`-style rules used by `path_rendering` (import it
  if exported; otherwise inline a conservative sanitizer: strip characters
  outside `[A-Za-z0-9 _'-]`, collapse whitespace, cap length 64).
- Movie variants: group videos by parent dir; variant labels
  `v1..vN` in sorted order; layout `movie_folder` if the dir is not the
  scan root else `movie_flat`.
- Asset ids: `imp-{sha256[:12]}` plus `-<k>` when the same content appears
  as multiple assets (k counts occurrences in sorted order).
- Sidecar language: filename `<stem>.<lang>.<ext>` where `<lang>` matches
  `[A-Za-z]{2,3}(-[A-Za-z0-9]+)?` and `<lang>` != a codec word; else
  default `"en"`.
- `duration_seconds` on each asset payload = `probed.duration_seconds`;
  `container` = the file's extension (lowercased, no dot).

```python
# emit.py
def emit_import_bundle(
    input_dir: Path,
    out: Path,
    works: list[ImportedWork],
    skips: list[SkipRecord],
    staged: list[tuple[Path, Path]],   # (source, bundle-dest) already decided
) -> ImportReport:
    """Stage media/, build the payload dict, dump YAML atomically, re-validate.

    Payload mirrors generation/api.py structure: schema_version
    SCENARIO_SCHEMA_VERSION, scenario_id f"import-{input_dir.name}-{yyyymmddhhmm}",
    seed 0, duration_scale "normal", library roots [{id: "main",
    path: sanitized input-dirname}], movies/series/artists from works,
    timeline from sidecar events. Re-validation runs prepare_run_input_from_bytes
    + run_validation (full pipeline). Any post-staging failure removes
    scenario.yaml and exactly the staged bundle names.
    """
```

Timeline events: `id=f"sidecar-{asset_id}-{n}"` (per-asset counter in sorted
sidecar order), `at="0s"`, subtitle events carry `kind="subtitle"`,
`language`, `codec` (from extension map), `body=<original text>`, `to`
rendered as `<stem>.<lang>.<ext-lowercase>`; NFO events carry
`kind="nfo"`, `body=<original text>`; poster events carry `kind="poster"`,
`media_type="image"`, `image_format` from extension (jpg→jpeg, png→png,
webp→webp), targeting the directory's lexicographically first imported asset.

**Tests** (no ffprobe): monkeypatch
`chaos_librarian.importer.probe_input.probe_file` to return canned
`ProbedMedia` from tiny fake files. Cover: movie folder with 2 variants +
`poster.jpg` + `Movie.en.srt` + `Movie.srt` (dedup: one subtitle event);
`Season 01/` tree with `S01E01` + unparseable `Episode 1.mkv` (skipped
`topology:no_anchor`) + duplicate `S01E01` (skipped
`topology:duplicate_episode`); `Season 01/` at scan root (all skipped
`topology:no_anchor`); `Artist/Album/01 Track.flac` and root-level `.flac`
(`topology:no_anchor`); `.cue` → `unrecognized`; `.avi` imports fine;
dedup mode drops second same-hash file (`mode:duplicate`); caps produce
`cap:*` reasons. Emit tests: re-validation runs (assert `run_validation`
called — monkeypatch wrapper), rollback removes exactly staged files on a
forced validation failure, deterministic ids across two runs.

**Verify:** `uv run pytest tests/importer -q`; guardrails; commit:
`feat(importer): scan, probe, topology, and scenario-bundle emission`.

---

## Task 6 — CLI `import` command + docs

**Files:** `src/chaos_librarian/cli/commands/import_media.py` (new),
`src/chaos_librarian/cli/commands/__init__.py`,
`src/chaos_librarian/cli/_envelope.py` (E_IMPORT_FAILED),
`tests/cli/test_import.py` (new), `tests/cli/test_app.py` (order list),
`docs/contract/cli-reference.md`, `docs/contract/schema-reference.md`,
`docs/user/commands.md`.

### Steps

1. **Envelope code:** `_envelope.py` add
   `E_IMPORT_FAILED = "E_IMPORT_FAILED"` beside `E_GENERATE_FAILED`.

2. **Command** (mirror `generate.py` structure exactly — envelope calls,
   `--json` handling, exit codes):

   ```python
   """``import`` command: scan an existing media library into a scenario bundle."""

   from __future__ import annotations

   from pathlib import Path
   from typing import Annotated

   import typer

   from chaos_librarian.cli._envelope import emit_cli_error
   from chaos_librarian.cli._render import validate_new_out_path
   from chaos_librarian.cli.app import app
   from chaos_librarian.importer.emit import emit_import_bundle
   from chaos_librarian.importer.probe_input import probe_inputs
   from chaos_librarian.importer.scan import scan_directory
   from chaos_librarian.importer.topology import build_topology
   from chaos_librarian.materializer.tooling.capabilities import detect_capabilities


   @app.command(name="import")
   def import_media(
       input_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
       out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
       mode: Annotated[str, typer.Option("--mode")] = "full",
       max_works: Annotated[int | None, typer.Option("--max-works")] = None,
       max_variants: Annotated[int, typer.Option("--max-variants")] = 4,
       max_duration_s: Annotated[float | None, typer.Option("--max-duration-s")] = None,
       json_output: Annotated[bool, typer.Option("--json")] = False,
   ) -> None:
       """Scan an existing media library and emit a scenario bundle."""
   ```

   Body flow: (1) `caps = detect_capabilities()` — if not
   `caps.ffprobe.ok`/meets-minimum (mirror `capabilities.py`'s check), emit
   error envelope and `raise typer.Exit(code=4)`; (2) validate `mode` ∈
   {full, sample, dedup} else `emit_cli_error(E_IMPORT_FAILED, ...)` exit 2
   (usage) — actually usage errors are Typer's domain: use
   `typer.BadParameter` for a bad `--mode` (exit 2); (3) scan → probe →
   topology → mode/cap filtering (sorted order, reasons per the taxonomy) →
   emit; (4) empty import (no works) → `emit_cli_error(E_IMPORT_FAILED,
   "no importable media found")` + exit 1; (5) success: `--json` prints the
   report dict, else human line `import: wrote <out> (<N> assets, <M>
   skipped)`. Wrap importer exceptions in
   `emit_cli_error(E_IMPORT_FAILED, str(exc))` + exit 1.

3. **Registration:** `cli/commands/__init__.py` add
   `from chaos_librarian.cli.commands import import_media` directly after
   the `generate` import (help order: validate, generate, **import**, plan, ...).
   Update `ALL_COMMANDS` in `tests/cli/test_app.py` to insert `"import"`
   after `"generate"`.

4. **CLI tests** (`tests/cli/test_app.py`-style, using typer's
   `CliRunner`): `--help` lists `import`; missing `--out` → exit 2;
   existing `--out` → exit 2 with "already exists"; empty input dir →
   exit 1 `E_IMPORT_FAILED` envelope (assert JSON `error_code` on stderr);
   `--json` success prints the report (fixture tree + stubbed prober via
   monkeypatch on the importer module — CLI tests must not need ffprobe:
   patch `chaos_librarian.cli.commands.import_media.probe_inputs`).

5. **Docs** (pinned by `tests/docs/test_documentation.py`):
   - `docs/contract/cli-reference.md`: add a `chaos-librarian import`
     section (command, options table, exit codes 0/1/2/4, bundle layout,
     skip-reason taxonomy) and ensure the exit-code table needs no change.
   - `docs/contract/schema-reference.md`: scenario row version 32 → 33
     (the version-table test pins `| scenario | 33 |`).
   - `docs/user/commands.md`: add a short `import` section.
   Run `uv run pytest tests/docs -q` — the doc-pinning tests must pass.

6. **Verify:** `uv run pytest tests/cli tests/docs -q`; full guardrails;
   commit: `feat(cli): import command with scenario-bundle emission`.

---

## Task 7 — End-to-end integration test (real tools)

**Files:** `tests/integration/import_real.py` (new; follows the
`tests/integration/*_real.py` naming so CI's real-tool job picks it up).

1. **Setup:** generate 2–3 tiny fixture media with ffmpeg (e.g.
   `color_bars` 1 s mp4, `sine` 0.5 s mp3) into a temp input dir; add
   `Movie.en.srt` text and a `poster.jpg` (ffmpeg-generated).
2. **Exercise:** run the import command (subprocess
   `uv run chaos-librarian import <dir> --out <tmp>/scenario.yaml --json`),
   assert exit 0 and report JSON; run `validate` (exit 0 — criterion 2);
   run `plan --out <tmp>/plan` (exit 0 — criterion 5); run `materialize`
   (exit 0); ffprobe the materialized mp4 and assert container/duration
   match the original within 0.05 s and codec matches (criterion 3);
   assert `Movie.en.srt` sidecar exists in the library with the original
   body text and the poster file exists (criterion 4).
3. **Verify:** `uv run pytest tests/integration -q` (requires
   ffmpeg/mkvtoolnix/ffprobe — the CI real-tool job runs it; locally skip
   is NOT allowed per that job's convention). Commit:
   `test(integration): end-to-end import-validate-plan-materialize`.

---

## Self-review checklist (completed at authoring time)

- Every spec requirement maps to a task: criterion 1 → Tasks 5–6;
  criterion 2 → Tasks 1–2, 5 (re-validation gate), 6 (docs);
  criterion 3 → Tasks 4, 7; criterion 4 → Tasks 2 (body), 4 (body branch),
  5, 7; criterion 5 → Tasks 1–2 (plan works on import scenarios — no
  timeline-engine change needed; verified by Task 7's plan run).
- Names cross-checked against source: `iter_asset_contexts` /
  `iter_assets_with_loc` (walkers.py), `Reporter`, `IssueCollector.add`,
  `_write_subtitle_sidecar`, `encode_subtitle_body`, `PhaseAInputs`,
  `ContentSourceEvidence`, `CacheDisposition.NOT_CACHEABLE`,
  `detect_capabilities`, `validate_new_out_path`, `ALL_COMMANDS`,
  `prepare_run_input_from_bytes`, `run_validation`,
  `is_safe_path_component`, `probe_file`, `MaterializedAsset`,
  `ToolInvocation`, `hashlib.file_digest` idiom from
  `_copy_same_content_asset`.
- `_iter_timeline_events` helper: confirmed used by
  `create_sidecar_content.py`; mirror its exact import in Task 2.
- Known open risk: `MaterializedAsset`/`PlanArtifacts` stub shapes in
  Task 4 tests — implementer should copy the construction pattern from the
  existing phase-A tests in `tests/materializer/content/` rather than
  inventing one.
