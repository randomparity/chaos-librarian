# Issue 86 Required Null Report Current Design

## Goal

Deleted assets must serialize `reports/assets/<asset_id>.json` with the required
nullable `current` field present as JSON `null`, so the checked-in report schema
and adapter loader agree with the bytes written by `plan`, `step`, and materialize
success paths.

## Root Cause

`AssetReport.current` is declared without a default as `AssetSnapshot | None`,
which makes it required and nullable in the exported schema. `engine.writer`
serializes every Pydantic artifact with `exclude_none=True`, so a deleted asset's
`current=None` is omitted from the on-disk report. Pydantic then rejects the
serialized report because a required field is missing.

`AssetSnapshot.location_path` has the same required-nullable shape. The immediate
reported failure is `current`, but the serializer should preserve any required
nullable field it writes instead of special-casing one report field.

## Options

1. Preserve required nulls in `canonical_json` while continuing to omit optional
   null defaults. This keeps the compact artifact style and makes serialized
   bytes match required-null schema fields everywhere this writer is used.
2. Special-case `AssetReport.current` in report writers only. This fixes the
   observed failure, but leaves other required-null fields vulnerable.
3. Make `AssetReport.current` optional by adding a default. This changes the
   adapter-facing contract to match broken bytes rather than the intended model.

Option 1 is the design choice.

## Design

Add a small recursive serializer in `src/chaos_librarian/engine/writer.py`.
It should:

- Start from each Pydantic model's JSON-mode dump with `exclude_none=False`.
- Walk the model fields in declared order.
- Use the serialized key already present in the JSON-mode dump so aliases stay
  identical to the current `by_alias=True` output.
- Omit `None` values only when the Pydantic field is not required.
- Preserve `None` values when the field is required.
- Recurse into nested `BaseModel` instances and lists/tuples of models.
- Leave dictionaries and primitive values as their JSON-mode dump values.

`canonical_json()` will use this serializer before
`json.dumps(indent=2, ensure_ascii=False)`. The function remains deterministic
because it walks model fields in declaration order and does not sort keys,
matching the previous Pydantic output style.

## Tests

Add a regression test that reproduces the issue using
`active-library-churn.yaml`: write a partial fixture, advance it through the
delete step, load the asset report JSON, and assert that `current` is present
with value `null`. The same test should validate the report through
`AssetReport` and load the full fixture through `load_fixture`.

Run focused writer/adapter tests, then ruff, ty, and schema drift checks before
opening the PR.
