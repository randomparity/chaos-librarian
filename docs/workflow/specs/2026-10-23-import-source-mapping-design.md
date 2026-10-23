# Import source mapping — issue #234

## Problem and authority

Import currently retains source-to-asset relationships internally but exports only
a scenario and summary report. Issue #234 requests an optional mapping artifact.
The operator approved campaign exclusions on 2026-10-23; the frozen charter is
[#234 scope](https://github.com/randomparity/chaos-librarian/issues/234#issuecomment-6375586374).
Complexity M, fixed denominator 250 changed lines; full-spec because this adds a
public option and artifact. Implementation awaits approval of this design.

## Proposed interface and data flow

Add `import --mapping-out PATH`, default absent. Emit UTF-8 JSON containing one
object whose keys are source media paths relative to the input directory, using
POSIX separators, and whose values are emitted asset ID strings. Example:
`{"Movie/Movie.mp4": "movie-main"}`. No absolute source root or metadata is included.
JSON escaping preserves unusual filenames; keys are sorted with two-space indent
and a trailing newline. The object itself is the complete artifact format.

Build the object from surviving `ImportedWork.asset_sources` after existing caps,
not from staged digests: full mode can map distinct sources to distinct asset IDs
while sharing one content-addressed bundle file. Dedup mode includes only its
accepted source. Skipped inputs and sidecar events have no mapping entry.
The same input tree, options and resulting topology produce identical mapping
bytes even though the existing scenario ID includes an import timestamp.

Extend `emit_import_bundle(..., *, mapping_out: Path | None = None)`; the CLI
passes the optional path. Existing report and scenario shapes stay unchanged.
The emitter remains the owner of import output publication; no move or duplicate
publisher is needed. Reuse its existing `_atomic_write` no-overwrite operation.
ADR 0012's bundle ownership and rollback boundary remain in force; no new ADR.

## Paths, publication, and errors

When specified, mapping parent must exist and be a directory. Reject an existing
mapping destination, including dangling symlinks. Resolve destinations for checks:
mapping must differ from the scenario path and must be outside both the input
directory and the scenario's `media/` directory (including symlink aliases).
These checks precede staging. The existing no-overwrite publisher is still the
final authority if another process creates the mapping after validation.

Stage bytes, publish scenario, validate/build report using the existing pipeline,
then atomically publish mapping before returning success. On ordinary exceptions,
remove only scenario, mapping and bundle files created by this attempt. Preserve
pre-existing files, including a racing mapping destination; no directory sweep.
Invalid mapping option paths use CLI usage exit 2. Publication/I/O failures use
the existing `E_IMPORT_FAILED` operational exit 1 and do not return a success report.

## Success

1. Omitted option produces the existing scenario/report and no mapping artifact.
2. Opt-in mapping has exactly the surviving imported-media source/asset pairs,
   including full/sample/dedup and work/variant/duration caps and duplicate bytes.
3. Existing/colliding destinations are preserved and rejected; failed mapping
   publication rolls back this import's newly created outputs.
4. A real-media import validates, plans, and materializes; its mapping IDs equal
   the scenario's media asset IDs and its keys identify the original media files.

## Failure model

- Actors and deployments: trusted local CLI operators and CI on the repository's
  supported Python platforms, reading local media trees and writing local files.
- Invariants/assets: original media and pre-existing outputs survive; source/ID
  relationships reflect final topology; success means the requested mapping exists.
- Accepted classes: process kill/power loss may leave outputs as in the existing
  importer (no cross-file crash transaction); malicious concurrent parent-directory
  replacement is outside this trusted local deployment; filesystem unlink failure
  may interrupt rollback and is surfaced by the existing operational error path.
- Covered elsewhere: probe/media fidelity and normal import caps belong to ADR
  0012 and existing tests; chaos generation belongs to #233; skipped-input IDs,
  sidecar preservation, report/schema redesign remain with repository maintainers.

## Threat model

- New boundary: operator-selected mapping destination; controls are early resolved
  collision/containment checks and existing atomic no-overwrite file publication.
- New disclosure: source-relative filenames intentionally leave the scan boundary
  only when requested; avoid absolute source root, preserve escaping in JSON.
- Untrusted filenames affect data only, not commands. No shell interpretation,
  probing changes, permissions changes or added dependencies.
- Out of scope: hostile filesystem actors replacing parent directories mid-run,
  and public upload/redaction of an operator-requested local artifact. No such
  service or upload is added; operators control artifact sharing.

## Alternatives and scope

Recommended: explicit `--mapping-out PATH` with a source-relative JSON object,
reusing final topology and existing publication. A fixed sibling filename is
simpler to invoke but gives the operator less control over an optional output.
Adding fields to the ordinary report conflates summary and mapping and contradicts
the approved unchanged-report scope. No full manifest or new schema machinery.

Exclusions/owners: chaos generation — #233; scenario schema, normal ImportReport,
oracle manifest, probes, original sidecar preservation, skipped-input mappings and
sidecar-event IDs — repository maintainers. No new deferred work is proposed.

## Validation

Focused CLI and emitter tests prove deterministic final-topology pairs, unchanged
default shapes, modes/caps/duplicate content, safe destination rejection, and
publication rollback. Extend the existing real import proof to read the mapping
and compare it with scenario IDs and source files. Documentation describes the
opt-in artifact, path convention, exclusions, privacy and failure behavior.
