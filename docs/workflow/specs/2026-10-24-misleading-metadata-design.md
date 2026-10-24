# Bounded misleading metadata (#246)

## Authority and outcome

Operator approval on 2026-10-24 authorizes format-tag evidence and the bounded
MKV corpus under #246 / epic #244. Existing generic edits remain available.
The journal records intent; probing records retained bytes, not consumer policy.
[ADR 0015](../../adr/0015-format-tag-evidence.md) chooses the evidence contract.

## Design

Extend `ProbedMedia` with `format_tags: dict[str, str] | None = None`.
The owned probe extracts only case-insensitive `title` and `year` into lowercase
keys. Values remain exact strings including present-empty. Missing tags become
an empty map; null means evidence was not supplied. Ignore other format tags,
including encoders, so tool versions do not cause meaningless differences.
A malformed selected value, duplicate case-insensitive selected key, or selected
value exceeding 4096 UTF-8 bytes fails probe mapping; do not coerce or truncate.
The adapter compares title/year only when both maps are supplied. Absent key
and empty string differ; missing evidence does not imply absence of a tag.
Existing generic tools and consumers can still supply other keys; comparison
ignores them. Bump manifest, asset-report and observed-state schema versions.

Bound edit_metadata values to 4096 UTF-8 bytes and reject C0 controls other than
TAB/LF, including NUL. Bound keys to 64 ASCII letters/digits/underscore/hyphen
and mappings to 16 entries; reject empty keys and `=` to keep argv unambiguous.
The existing nonempty mapping rule stays. Do not restrict ordinary keys or
containers. Bump scenario and replay-bundle versions and migrate fixtures.
Empty values request removal; this does not assert that a muxer stores empty.

The supported pathological corpus uses MKV/H.264/AAC, short duration scale,
SD video, <=30 seconds, <=2 audio tracks and <=64 MiB per output. Fixture tests
assert those limits. Fixed seed 246 and <=7 one-second cases bound selection.
The cases are filename versus title, NFO title versus embedded title,
year 9999, long title at the UTF-8 limit, Unicode with LF/TAB, removed/missing
metadata, and two streams with conflicting eng/fra language labels. The
language case is a separate asset from edits. No explicit #245 dispositions.
Existing title/year ordinary fixtures are the paired controls. No assertion
of semantic language correctness for synthesized sine audio.

Use existing materialize/run/replay entry points. Actual-file ffprobe assertions
must match recorded supported tags, NFO XML and filenames, and raw stream labels.
Replay must retain requested fields and reproduce these properties. Comparisons
must detect changed title/year or stream language; do not add downstream policy.
No new generation profile or framework. #248 owns aggregate scheduling and CI.
Metadata cases run through the existing equipped integration glob.

## Failure model

- Actors/deployments: local scenario authors, equipped CLI operators and CI.
- Invariants/assets: requested versus observed truth; missing versus empty;
  bounded local fixture cost; schema drift; existing containment and cleanup.
- Accepted classes: pathological metadata outside the named MKV matrix has no
  retained-value guarantee; ordinary generic edits keep their existing behavior.
  Encoder byte differences across versions are accepted. Probe success does not
  claim decodability. Concurrent hostile modification of private run directories
  remains outside this local synthetic-fixture deployment.
- Covered elsewhere: flags #245; corruption #247; seeded scheduling/combined
  corpus/coverage budgets #248; consumer precedence and recovery consumers;
  exhaustive codecs and a mutation framework future operator-authorized work.

## Threat model

- Added boundary: selected ffprobe tags enter public oracle evidence. Narrow
  extraction, string validation and byte bounds prevent invented/truncated data.
- Widened boundary: authored metadata values passed to the existing argv-only
  ffmpeg boundary; key/value/count checks reject NUL and ambiguous key=value
  operands. Leading hyphens are safe inside the metadata operand.
- Actors: local authors control input; installed media tools are trusted to
  execute. Existing path containment, timeouts and atomic temporary outputs
  remain owners; tests prove failure leaves no successful published run.
- Out of scope: malicious installed tools and network services are not part of
  the deployment. No secrets, network endpoints or permissions added.

## Validation and constraints

Python >=3.13; ffmpeg/ffprobe >=7; no dependencies or tool-floor changes.
Use focused parser/schema/adapter tests for missing, empty, malformed,
case normalization, long Unicode, unsupported controls and boundary lengths.
Real-tool tests inspect generated files directly with a 15-second probe timeout
and 1 MiB output limit. Fixture media tools keep the existing 60-second runtime
bound; corpus input sizes and stream counts bound expected output. Reject tool
failures through existing outcomes, never count normalized tags as coverage.
Run standard/equipped suites and existing lint/type/schema checks. No AI surface.
