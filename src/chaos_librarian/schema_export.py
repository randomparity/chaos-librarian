"""Export Pydantic v2 models to JSON Schema (draft 2020-12) artifacts.

Usage:
    python -m chaos_librarian.schema_export --write    # regenerate schemas/
    python -m chaos_librarian.schema_export --check    # fail on drift (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel, TypeAdapter

from chaos_librarian.contract.journal import JournalEntry  # Annotated union
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import MaterializationReport
from chaos_librarian.contract.replay_bundle import ReplayBundle  # Annotated union
from chaos_librarian.contract.reports import (
    AssetReport,
    BundleReport,
    VariantReport,
    WorkReport,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationReport

# (filename, model-or-adapter). Filenames are public contract; do not rename.
# Discriminated unions are wrapped in TypeAdapter so model_json_schema is not
# accessible on the bare Annotated alias.
MODELS: Final[list[tuple[str, object]]] = [
    ("scenario.schema.json", Scenario),
    ("manifest.schema.json", Manifest),
    ("journal.schema.json", TypeAdapter(JournalEntry)),
    ("replay-bundle.schema.json", TypeAdapter(ReplayBundle)),
    ("validation.schema.json", ValidationReport),
    ("materialization.schema.json", MaterializationReport),
    ("run-sentinel.schema.json", RunSentinel),
    ("asset-report.schema.json", AssetReport),
    ("work-report.schema.json", WorkReport),
    ("variant-report.schema.json", VariantReport),
    ("bundle-report.schema.json", BundleReport),
]


def _schema_for(model_or_adapter: object) -> dict[str, object]:
    if isinstance(model_or_adapter, TypeAdapter):
        return model_or_adapter.json_schema(mode="serialization")
    if not (isinstance(model_or_adapter, type) and issubclass(model_or_adapter, BaseModel)):
        raise TypeError(
            f"Expected BaseModel subclass or TypeAdapter, got {type(model_or_adapter).__name__}"
        )
    return model_or_adapter.model_json_schema(mode="serialization")


def _serialize(schema: dict[str, object]) -> str:
    # Stable, sorted, trailing newline so diffs are clean.
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def write_all(schemas_dir: Path) -> None:
    """Regenerate every schema under ``schemas_dir`` atomically.

    Each file is written to a sibling ``<filename>.tmp`` and renamed into
    place. The drift gate in CI compares byte-for-byte, so a partial write
    interrupted by SIGINT or disk-full must never leave a half-written
    schema file behind.
    """
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS:
        target = schemas_dir / filename
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(_serialize(_schema_for(model)))
        tmp.replace(target)


def check_all(schemas_dir: Path) -> list[str]:
    """Return a list of filenames that diverge from current models."""
    drift: list[str] = []
    for filename, model in MODELS:
        path = schemas_dir / filename
        if not path.exists():
            drift.append(f"{filename} (missing)")
            continue
        current = _serialize(_schema_for(model))
        on_disk = path.read_text()
        if current != on_disk:
            drift.append(filename)
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or check JSON Schema artifacts.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="Regenerate schemas/")
    group.add_argument("--check", action="store_true", help="Fail if schemas/ is stale")
    parser.add_argument(
        "--dir",
        type=Path,
        default=_repo_root() / "schemas",
        help="Schema directory (default: <repo>/schemas/)",
    )
    args = parser.parse_args(argv)

    if args.write:
        write_all(args.dir)
        print(f"Wrote {len(MODELS)} schemas to {args.dir}")
        return 0

    drift = check_all(args.dir)
    if drift:
        print("Schema drift detected:", file=sys.stderr)
        for name in drift:
            print(f"  - {name}", file=sys.stderr)
        print("Run: python -m chaos_librarian.schema_export --write", file=sys.stderr)
        return 1
    print(f"All {len(MODELS)} schemas up-to-date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
