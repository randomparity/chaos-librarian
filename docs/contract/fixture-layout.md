# Fixture Directory Layout

Each chaos-librarian run writes a self-contained fixture directory protected
by a `.chaos-librarian-run` sentinel file. See
[`chaos-librarian-design.md` "Fixture Directory Layout"](../specs/chaos-librarian-design.md)
and "Filesystem Safety" for the full contract.

```text
run/
  .chaos-librarian-run        # sentinel — REQUIRED, validated by `clean`
  scenario.yaml
  replay.json
  manifest.initial.json
  manifest.current.json
  journal.jsonl
  validation.json
  materialization.json
  reports/
    assets/
    works/
    variants/
    bundles/
  library/                    # all scenario paths resolve under here
    movies-hd/
    movies-4k/
    archive/
    staging/
```

Path-containment rules: every scenario path resolves under `<run-dir>/library/`
after symlink/`..` normalization. Violations fail with exit code `7`.

## Plan-Only Subset

Plan-only runs write every oracle artifact except `materialization.json` and
`library/`. The `reports/` tree is part of plan output and is updated by
`step`.

`reports/` are written by plan, materialize, and run outputs.

## Malformed-Media Fixtures

Malformed-media scenarios are ordinary fixtures with explicit profile opt-in:

```yaml
profiles:
  - malformed-media
```

When `corrupt_container_header` runs, the final manifest version and the
matching asset report snapshot carry a `corruption` record with the profile,
event id, corruptor name, byte range, and seed material. `materialization.json`
also includes one `corruption_actions[]` entry with input/output hashes and the
probe outcome. A probe failure after intentional corruption is success evidence,
not a materialization failure.

## External Observed State

`observed-state.json` is not written into the fixture directory by Chaos
Librarian. It is an external consumer export passed to:

```bash
chaos-librarian compare run/ observed-state.json --json
```

The compare command validates the fixture first, then validates the external
observed-state input against `observed-state.schema.json`.
