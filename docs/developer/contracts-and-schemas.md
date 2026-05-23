# Contracts and Schemas

Pydantic v2 models in `src/chaos_librarian/contract/` are the source of truth
for public contracts. Do not hand-edit files under `schemas/`.

`schema_export.py` writes JSON Schema draft 2020-12 artifacts under `schemas/`.
Run this after any contract model edit:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Before committing, verify checked-in artifacts are current:

```bash
uv run python -m chaos_librarian.schema_export --check
```

Schema-version constants live in `contract/__init__.py`. They are breaking
contract versions; bump the matching constant when a required public field,
mode, or artifact contract changes.

Several contracts intentionally use discriminated unions. Scenario timeline
events discriminate on `action`. Journal entries discriminate on `phase`.
Replay bundles discriminate on `execution_mode`, and execution trace entries
discriminate on `kind`. These export as `oneOf` with `discriminator` so
non-Python consumers can validate the same mode splits.
