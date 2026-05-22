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

Plan-only runs (Sprint 3) write a strict subset of the full layout:

- `.chaos-librarian-run` (sentinel)
- `scenario.yaml`
- `replay.json`
- `manifest.initial.json`
- `manifest.current.json`
- `journal.jsonl`
- `validation.json`

`materialization.json`, `library/`, and `reports/` are written by later
sprints (5 / 6+ / 4 respectively).

## External Observed State

`observed-state.json` is not written into the fixture directory by Chaos
Librarian. It is an external consumer export passed to:

```bash
chaos-librarian compare run/ observed-state.json --json
```

The compare command validates the fixture first, then validates the external
observed-state input against `observed-state.schema.json`.
