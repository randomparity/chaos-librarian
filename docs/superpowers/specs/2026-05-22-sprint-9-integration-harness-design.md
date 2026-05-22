# Sprint 9 - Integration Harness And Consumer-Neutral Adapter

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Sprint 9 - Integration Harness And voom-v2 Adapter", "Oracle IDs",
"Oracle Journal", "Schema Contract", and "Mitigations For Late voom-v2
Integration").
**Predecessor:** Sprint 8 (`feat/sprint-8`, merged on `main`) implemented
wall-clock `run`, daemon-friendly scheduling, and run-mode replay support.
**Target branch:** `feat/sprint-9`.

## Goal

Sprint 9 turns Chaos Librarian's oracle artifacts into a consumer-facing
comparison harness. The adapter remains consumer-neutral: applications export
their observed library state into a stable JSON shape, and Chaos Librarian
compares that observation against the fixture oracle.

The sprint ships:

1. `chaos_librarian.adapter` as a Python package for test suites.
2. `observed-state.schema.json` as the consumer-export contract.
3. `divergence.schema.json` as the comparison report contract.
4. `chaos-librarian compare <run-dir> observed-state.json --mode final-state
   --json` as a thin CLI wrapper over the Python API.
5. Recipe docs for scanner, prober, watcher, daemon churn, and CI profiles.

Exit criteria:

- A consumer can compare its observed state against a plan, materialize, or run
  fixture without importing consumer-specific code into Chaos Librarian.
- Divergence reports identify the oracle asset, optional event, observed
  consumer reference, expected value, observed value, and evidence used for the
  match.
- Short comparison recipes are fast enough for regular development.

## Decisions Resolved In Brainstorming

1. **Adapter ownership.** The adapter lives in Chaos Librarian and is
   consumer-neutral. voom-v2 or any other application owns its exporter into
   `observed-state.json`; Chaos Librarian owns oracle loading, matching, and
   divergence reporting.

2. **Observed-state contract.** Add `observed-state.schema.json` rather than
   accepting unstructured application payloads. A schema gives consumers a stable
   target and keeps the adapter independent of voom-v2's SQLite tables.

3. **Comparison surface.** Add both a Python API and a CLI. The CLI is a thin
   wrapper around the API so test suites can import the library while CI scripts
   and non-Python consumers still have a stable, agent-friendly command.

4. **Comparison modes.** The compare API and CLI select the comparison mode;
   the observed-state payload stays reusable data. `final-state` is the default
   for scanner/prober tests. `identity-history` is opt-in for watcher and
   reconciliation tests and requires lifecycle evidence through `events` or
   per-asset `path_history`.

5. **Oracle-ID mapping.** Consumers do not have to store Chaos Librarian oracle
   IDs. They provide their own stable `observed_ref` values and observed facts.
   The adapter infers matches from deterministic evidence: current path,
   historical paths, content hash, and topology.

6. **Divergence as data, not command failure.** A valid comparison with
   differences returns a `DivergenceReport` with `ok: false`. The CLI exits `6`
   for this case, matching existing replay divergence semantics. Malformed
   inputs and unsafe fixture access still use the existing CLI error envelope on
   stderr.

7. **No voom-v2 reader this sprint.** A direct voom-v2 SQLite reader is out of
   scope. That would couple Chaos Librarian to a consumer schema and weaken the
   neutral-oracle boundary.

## Scope

### In Scope

- Add Pydantic contract models for observed state and divergence reports.
- Export `observed-state.schema.json` and `divergence.schema.json`.
- Add schema version constants:
  - `OBSERVED_STATE_SCHEMA_VERSION: Final = 1`
  - `DIVERGENCE_SCHEMA_VERSION: Final = 1`
- Add `chaos_librarian.adapter` with fixture loading, observed-state loading,
  deterministic matching, and report generation.
- Add `chaos-librarian compare <run-dir> observed-state.json --mode
  final-state|identity-history --json`.
- Compare current asset paths, deleted/missing assets, content hashes, probed
  media facts, path history, and optional topology references.
- Include sidecar path/hash comparison when consumers export sidecar observations.
- Add docs with exporter recipes and CI guidance.

### Out Of Scope

- Reading voom-v2 databases directly.
- Predicting application policy outcomes.
- Requiring consumers to persist Chaos Librarian oracle IDs.
- A new fuzzing profile or corruption profile.
- Live streaming comparison while `run` is still in progress.
- Adding new media mutations or changing scenario semantics.
- Replacing replay fixture-vs-fixture diff internals.

## Architecture

Add a small adapter package beside the existing engine and materializer layers:

```text
src/chaos_librarian/
  adapter/
    __init__.py          # public API exports
    fixture.py           # load_fixture(run_dir) -> OracleFixture
    observed.py          # load_observed_state(path) -> ObservedState
    index.py             # oracle/observed evidence indexes
    matching.py          # deterministic asset matching
    compare.py           # compare_fixture_to_observed(...) -> DivergenceReport
    errors.py            # AdapterInputError

src/chaos_librarian/contract/
  observed_state.py      # ObservedState and supporting models
  divergence.py          # DivergenceReport and supporting models

src/chaos_librarian/cli/commands/
  compare.py             # thin wrapper over adapter.compare
```

The adapter imports contract and engine readers. It does not import
materializer execution code except for shared contract types such as
`ProbedMedia`. The engine remains pure; the adapter does not mutate fixture
directories or application state.

`OracleFixture` is an internal dataclass, not a schema artifact. It carries:

- `run_dir`
- parsed sentinel
- parsed replay bundle
- initial manifest
- current manifest
- journal entries
- per-entity reports, loaded when present

The fixture loader validates sentinel presence and fixture consistency before
comparison. Missing optional `reports/` should not block comparison if the
manifest and journal are sufficient, but malformed present reports are an input
error because they make the fixture untrustworthy.

## Observed-State Contract

`ObservedState` is the JSON shape consumers export. Paths are library-relative
POSIX paths using the same convention as `ManifestLocation.path`; exporters must
strip local mount prefixes before writing the payload. Observed paths must be
relative paths without `..` segments.

Contract model shape:

```python
class ObservedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    consumer: ObservedConsumer
    run_id: uuid.UUID
    observed_at: datetime
    assets: list[ObservedAsset]
    works: list[ObservedWork] = Field(default_factory=list)
    variants: list[ObservedVariant] = Field(default_factory=list)
    bundles: list[ObservedBundle] = Field(default_factory=list)
    events: list[ObservedEvent] = Field(default_factory=list)


class ObservedConsumer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None


class ObservedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    current_path: str | None
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    probed: ProbedMedia | None = None
    work_ref: str | None = None
    variant_ref: str | None = None
    bundle_ref: str | None = None
    sidecars: list[ObservedSidecar] = Field(default_factory=list)
    path_history: list[ObservedPathHistoryEntry] = Field(default_factory=list)


class ObservedSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    kind: str
    path: str
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class ObservedWork(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    title: str | None = None


class ObservedVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    work_ref: str | None = None
    label: str | None = None


class ObservedBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    variant_ref: str | None = None
    asset_refs: list[str] = Field(default_factory=list)
    sidecar_refs: list[str] = Field(default_factory=list)
```

The implementation plan can split the supporting classes into focused files, but
the wire contract must keep these semantics:

- `observed_ref` is consumer-owned and stable within the payload.
- `current_path=None` means the consumer believes the asset is absent/deleted.
- `content_hash` and `probed` are optional because scanner-only consumers may
  not hash or probe.
- Topology fields are optional. When supplied, they improve matching and produce
  topology mismatch findings.
- Sidecars are nested under the observed asset because the Chaos Librarian
  manifest also binds sidecars to `asset_id`.
- `path_history` is per-asset and ordered by observation time.
- `assets[].observed_ref`, `works[].observed_ref`, `variants[].observed_ref`,
  and `bundles[].observed_ref` are unique within their own collection.
- `sidecars[].observed_ref` is unique within the parent asset's sidecar list.
- When topology refs are supplied, they must point to supplied observed objects:
  asset `work_ref`, `variant_ref`, and `bundle_ref`; variant `work_ref`; bundle
  `variant_ref`; bundle `asset_refs`; and bundle `sidecar_refs`.
- `ObservedBundle.sidecar_refs` resolve against the sidecars nested under the
  bundle's `asset_refs`. A sidecar ref must match exactly one sidecar in that
  asset set.
- Duplicate refs, ambiguous sidecar refs, and dangling refs make the
  `ObservedState` an input error, not a divergence finding.

Observed path history:

```python
class ObservedAction(enum.StrEnum):
    MOVE = "move"
    RENAME = "rename"
    DELETE_READD = "delete_readd"
    SLOW_COPY = "slow_copy"
    ARCHIVE = "archive"
    ROOT_MOVE = "root_move"


class ObservedPathHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_event_ref: str | None = None
    action: ObservedAction
    observed_at: datetime | None = None
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
```

Observed events provide a consumer-global alternative for watcher exports that
do not naturally attach history to asset records:

```python
class ObservedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_event_ref: str
    observed_ref: str | None = None
    before_observed_ref: str | None = None
    after_observed_ref: str | None = None
    action: ObservedAction
    observed_at: datetime | None = None
    path: str | None = None
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
```

History actions are a fixed consumer-neutral vocabulary. The adapter rejects
unknown actions instead of normalizing aliases. Per-action path requirements are:

- `move`, `rename`, `delete_readd`, `archive`, and `root_move` require
  `from_path` and `to_path`.
- `slow_copy` requires `from_path` and `to_path`; `temp_path` is optional.

Global `ObservedEvent` entries must also identify the consumer lifecycle being
described: either `observed_ref`, or both `before_observed_ref` and
`after_observed_ref`, must be present. Missing per-action fields or missing ref
evidence make the `ObservedState` an input error.

The adapter treats `events` and `assets[].path_history` as additive evidence.
In `final-state` mode, if neither is present, history assertions are skipped and
the report covers final state only. `observed-state.json` does not carry the
comparison mode; the same export can be reused for `final-state` and
`identity-history` comparisons.

In `identity-history` mode, the payload must provide enough lifecycle evidence
to prove continuity across oracle path mutations. A stable `observed_ref` with
ordered `path_history` proves continuity for one consumer asset. A consumer that
records old and new refs separately can prove or expose continuity through
global `events` with `before_observed_ref` and `after_observed_ref`.
If per-asset history and global events make contradictory claims for the same
oracle path mutation, the adapter fails closed with `D_HISTORY_CONFLICT` rather
than choosing one source as authoritative.
`identity-history` never silently downgrades to final-state behavior.

## Divergence Report Contract

`DivergenceReport` is a comparison artifact, not a CLI error envelope. A report
with `ok=false` is a successful comparison that found differences.

Contract model shape:

```python
class DivergenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    run_id: uuid.UUID
    mode: CompareMode
    ok: bool
    fixture: DivergenceFixtureMetadata
    observed: DivergenceObservedMetadata
    findings: list[DivergenceFinding] = Field(default_factory=list)


class DivergenceFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: DivergenceCode
    severity: DivergenceSeverity
    message: str
    oracle_asset_id: str | None = None
    oracle_event_id: str | None = None
    observed_ref: str | None = None
    expected: object | None = None
    observed: object | None = None
    evidence: list[MatchEvidence] = Field(default_factory=list)
```

`ok` is derived from the findings: `ok == not any(f.severity == "error" for f in
findings)`. Model validation rejects reports where `ok` disagrees with the
presence or absence of error findings. Sprint 9 emits `"error"` for every listed
initial finding code, so any Sprint 9 finding makes `ok=false`.

Initial finding codes:

- `D_ASSET_MISSING` - an oracle asset has no observed match.
- `D_ASSET_UNEXPECTED` - an observed asset has no oracle match.
- `D_MATCH_AMBIGUOUS` - evidence maps an observed asset to multiple plausible
  oracle assets or vice versa.
- `D_PATH_MISMATCH` - matched asset path differs from oracle current path.
- `D_DELETION_MISMATCH` - one side thinks the asset exists and the other does
  not.
- `D_HASH_MISMATCH` - both sides supplied hashes and they differ.
- `D_PROBE_MISMATCH` - both sides supplied probed facts and the defined probe
  comparison fields differ.
- `D_SIDECAR_MISSING` - oracle sidecar missing from observed sidecars.
- `D_SIDECAR_UNEXPECTED` - observed sidecar not present in the oracle.
- `D_TOPOLOGY_MISMATCH` - work/variant/bundle grouping differs when both sides
  supplied topology.
- `D_IDENTITY_SPLIT` - one oracle asset lifecycle maps to multiple observed
  asset refs across a move, rename, delete/re-add, or slow-copy boundary.
- `D_HISTORY_CONFLICT` - per-asset history and global events make contradictory
  claims about the same oracle path mutation.
- `D_HISTORY_MISSING` - identity-history mode has no observed lifecycle evidence
  for an expected path mutation.
- `D_HISTORY_UNEXPECTED` - observed history contains a path mutation that does
  not map to the oracle journal.

`severity` is `"error"` for state differences that fail the comparison and
`"warning"` for partial evidence that should be surfaced but may not fail by
itself. Sprint 9 emits `"error"` for every listed initial code. Warning findings
require their own explicit future code rather than reclassifying an error code.

`MatchEvidence` records why a match was made:

```python
class MatchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["current_path", "historical_path", "content_hash", "topology"]
    value: str
    oracle_asset_id: str | None = None
    observed_ref: str | None = None
```

`oracle_event_id` always refers to the current journal/report contract:
`JournalEntry.event_id`, `AssetHistoryEntry.event_id`, `PathHistoryEntry.event_id`,
or `VersionHistoryEntry.event_id`. Sprint 9 does not introduce a separate
mutation identifier.

## Matching Rules

Matching is deterministic and evidence-ranked. It must never average conflicting
evidence into a silent best guess.

Precedence:

1. Exact current path.
2. Historical path from oracle `AssetReport.path_history`, journal
   `state_delta`, or observed path history.
3. Exact content hash when both sides supply one.
4. Topology match when both sides provide work, variant, or bundle grouping.

Rules:

- A unique match at a higher precedence wins over lower-precedence evidence.
- Conflicting lower-precedence evidence on an already matched pair becomes a
  mismatch finding, not a rematch.
- If one observed asset maps to multiple oracle assets at the same precedence,
  emit `D_MATCH_AMBIGUOUS`.
- If one oracle asset maps to multiple observed assets at the same precedence,
  emit `D_MATCH_AMBIGUOUS`.
- Unmatched oracle assets emit `D_ASSET_MISSING`.
- Unmatched observed assets emit `D_ASSET_UNEXPECTED`.
- Deleted assets can still match by historical path or hash; after matching,
  existence disagreement emits `D_DELETION_MISMATCH`.

This matching model keeps scanner tests ergonomic while still explaining why a
watcher or reconciliation test failed.

## Comparison Modes

`final-state` mode is the default. It compares current oracle state against
current observed state and does not fail because history evidence is missing. A
consumer that only exports `observed_ref` and `current_path` can use this mode.

`identity-history` mode adds lifecycle assertions for durable identity. It still
performs all final-state checks, then inspects oracle path-affecting journal
events and observed history. For every oracle move, rename, delete/re-add,
slow-copy, archive, or root-move event, the observed payload must show one of:

- the matched observed asset has a `path_history` entry representing the same
  path transition; or
- a global `ObservedEvent` represents the transition and keeps
  `before_observed_ref == after_observed_ref`; or
- a global `ObservedEvent` represents a split with different before/after refs,
  which emits `D_IDENTITY_SPLIT`.

If identity-history mode is requested and the observed payload has no history
evidence, the adapter emits `D_HISTORY_MISSING` findings for expected path
mutations instead of silently downgrading to final-state comparison.

When history sources disagree, contradiction wins over inference. For a given
oracle path mutation, the adapter evaluates all matching per-asset history and
global events. If one source proves continuity while another proves different
before/after observed refs, emit `D_HISTORY_CONFLICT` for that oracle event.
Emit `D_IDENTITY_SPLIT` only when the available evidence consistently shows the
oracle lifecycle mapped to multiple observed refs. Do not emit both
`D_HISTORY_CONFLICT` and `D_IDENTITY_SPLIT` for the same oracle event.

## Comparison Data Flow

```text
chaos-librarian compare fixtures/run-001 observed-state.json --mode final-state --json
  cli.commands.compare
    load_fixture(run_dir)
      validate sentinel
      parse replay.json
      parse manifest.initial.json and manifest.current.json
      parse journal.jsonl
      parse reports/ when present
    load_observed_state(path)
      validate observed-state schema
    compare_fixture_to_observed(fixture, observed)
      verify run_id equality
      select final-state or identity-history mode
      build oracle evidence indexes
      build observed evidence indexes
      match assets deterministically
      compare final state
      compare optional sidecars
      compare optional topology
      compare optional history
      return DivergenceReport with mode set to the selected comparison mode
```

`observed.run_id` must match the fixture replay bundle's `run_id`. A mismatch is
an input error, not a divergence finding, because the comparison target is the
wrong run.

For materialize/run fixtures, cross-toolchain comparison should reuse
`contract.canonicalize` semantics where appropriate: content hashes and probed
facts are compared only when the observed payload supplies them. Missing optional
hash/probe fields are not divergence by themselves.

Probe comparison is intentionally field-specific. `D_PROBE_MISMATCH` compares
these fields exactly when both sides supply `probed`: container, stream count,
stream order, stream kind, codec, language, width, height, channels,
sample_rate, default, and forced. `duration_seconds` is compared with a small
documented tolerance of `0.05` seconds. `size_bytes` is ignored by probe
comparison because byte-level differences are covered by `content_hash` and file
size checks when consumers export them.

## Python API

Public API:

```python
class CompareMode(enum.StrEnum):
    FINAL_STATE = "final-state"
    IDENTITY_HISTORY = "identity-history"


def load_fixture(run_dir: Path) -> OracleFixture: ...

def load_observed_state(path: Path) -> ObservedState: ...

def compare_fixture_to_observed(
    fixture: OracleFixture,
    observed: ObservedState,
    *,
    mode: CompareMode = CompareMode.FINAL_STATE,
) -> DivergenceReport: ...
```

Errors:

```python
class AdapterInputError(ChaosLibrarianError):
    error_code: str
    message: str
    details: dict[str, object]
```

Initial adapter input error codes:

- `E_ADAPTER_FIXTURE_INVALID`
- `E_ADAPTER_OBSERVED_INVALID`
- `E_ADAPTER_RUN_ID_MISMATCH`

These are command failures when surfaced through the CLI.

## CLI

Add a new command:

```text
chaos-librarian compare fixtures/run-001 observed-state.json --mode final-state --json
```

Arguments:

- `run_dir`: existing directory, must contain a valid Chaos Librarian sentinel.
- `observed`: existing JSON file, must validate as `ObservedState`.
- `--mode`: `final-state` by default, or `identity-history` for watcher and
  durable-identity checks.
- `--json`: follows the existing command convention.

Success and divergence behavior:

- Exit `0`, stdout `DivergenceReport` with `ok=true` when no findings fail the
  comparison.
- Exit `6`, stdout `DivergenceReport` with `ok=false` when comparison completes
  and finds divergence.
- Exit `1` with the existing CLI error envelope on stderr for malformed observed
  JSON, schema-invalid observed payloads, run-id mismatch, or invalid fixture
  artifacts.
- Exit `7` with the existing CLI error envelope on stderr for sentinel or
  filesystem safety errors.

Human output can be brief:

```text
compare: ok (0 findings)
```

or:

```text
compare: divergence (3 findings)
  D_ASSET_MISSING asset_001
  D_PATH_MISMATCH asset_002 observed=file_asset:42
```

The JSON path is the primary contract.

## Documentation Recipes

Add consumer-facing docs under `docs/contract/`:

- `observed-state.md` - neutral exporter contract and examples.
- `divergence-report.md` - report fields, codes, and exit semantics.
- `integration-recipes.md` - short scanner, prober, watcher, daemon churn, and
  CI examples.

Recipe guidance:

- Scanner recipe exports `observed_ref` and `current_path` only.
- Prober recipe adds `content_hash` and `probed`.
- Watcher recipe adds `path_history` or `events` and uses
  `--mode identity-history`.
- Daemon churn recipe runs `chaos-librarian run`, lets the consumer daemon
  observe the library, exports observed state, then compares.
- Fast CI uses a short static or small mutation scenario.
- Extended CI uses wall-clock churn and media mutations when capabilities allow.

The recipes should not implement voom-v2-specific code. They should show the
shape a voom-v2 exporter would write.

## Testing

Contract tests:

- `ObservedState` round-trips valid scanner, prober, and watcher payloads.
- `ObservedState` rejects extra fields, invalid hash syntax, missing
  `observed_ref`, and absolute paths.
- `ObservedState` rejects unknown history actions and missing per-action path
  fields.
- `ObservedState` rejects duplicate observed refs within each declared uniqueness
  scope.
- `ObservedState` rejects dangling topology refs, dangling sidecar refs, and
  ambiguous bundle sidecar refs.
- `DivergenceReport` round-trips `mode="final-state"` findings with
  expected/observed values and match evidence.
- `DivergenceReport` round-trips `mode="identity-history"` findings with
  expected/observed values and match evidence.
- `DivergenceReport` rejects `ok=true` with error findings and `ok=false` with no
  error findings.
- Schema export includes `observed-state.schema.json` and
  `divergence.schema.json`.
- Schema version constants are positive integers and equal to `1`.

Adapter behavior tests:

- Clean observed state generated from a fixture returns `ok=true`.
- Missing observed asset produces `D_ASSET_MISSING`.
- Unexpected observed asset produces `D_ASSET_UNEXPECTED`.
- Current path mismatch produces `D_PATH_MISMATCH`.
- Existence disagreement produces `D_DELETION_MISMATCH`.
- Hash mismatch produces `D_HASH_MISMATCH` only when both sides provide hashes.
- Probe mismatch produces `D_PROBE_MISMATCH` only when both sides provide
  probed facts, using the exact/tolerant/ignored field rules above.
- Ambiguous same-path or same-hash evidence produces `D_MATCH_AMBIGUOUS`.
- Missing observed sidecar produces `D_SIDECAR_MISSING`.
- Final-state-only comparison skips history checks.
- Identity-history comparison with no history evidence emits `D_HISTORY_MISSING`
  instead of silently running as final-state comparison.
- Identity-history comparison reports `D_HISTORY_MISSING` for a missing move or
  rename observation.
- Identity-history comparison reports `D_IDENTITY_SPLIT` when a move or rename
  maps one oracle asset to different before/after observed refs.
- Identity-history comparison reports `D_HISTORY_CONFLICT` when per-asset
  history and global events contradict each other for the same move or rename.
- `DivergenceFinding` round-trips with `oracle_event_id`.

CLI tests:

- Clean compare exits `0` and writes the report to stdout.
- Divergent compare exits `6` and writes the report to stdout.
- Identity-history comparison with no history evidence exits `6` and writes a
  `D_HISTORY_MISSING` report to stdout.
- Malformed observed JSON uses the CLI error envelope on stderr.
- Run-id mismatch is an adapter input error, not a divergence report.
- Missing or malformed sentinel uses existing sentinel error behavior.

## Risks And Mitigations

- **Ambiguous identity.** Paths and hashes can both collide in synthetic
  fixtures. The adapter must emit ambiguity instead of choosing arbitrarily.
- **Consumer path normalization.** Different applications may store absolute
  paths, mount paths, or remote paths. The contract requires library-relative
  POSIX paths so the adapter does not guess path maps.
- **Overfitting to voom-v2.** The schema names use generic `observed_ref` and
  optional topology fields, not voom table names.
- **History availability.** Some consumers cannot export event history.
  `final-state` keeps history optional; `identity-history` turns missing
  lifecycle evidence into `D_HISTORY_MISSING` instead of downgrading.
- **Report sprawl.** Start with a small fixed finding-code vocabulary. Add codes
  only when tests prove a distinct failure mode needs a distinct diagnosis.

## Alternatives Rejected

1. **Python API only.** Smaller, but weak for CI scripts and non-Python
   consumers. The CLI is cheap because it wraps the same API.

2. **voom-v2-specific SQLite adapter.** Faster for one consumer, but it couples
   Chaos Librarian to voom-v2's schema and contradicts the neutral oracle model.

3. **Require consumers to store oracle IDs.** This would make matching trivial
   but unrealistic for scanner and watcher workflows. The adapter's purpose is
   to compare what the application actually observed.

4. **Always require event history.** Too heavy for scanner/prober tests and not
   needed to validate final reconciliation.

5. **Reuse the CLI error envelope for divergence.** Errors and comparison
   findings are different domains. Divergence needs a schema artifact because it
   is a report consumers inspect, store, and gate on.
