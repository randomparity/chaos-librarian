"""Fixture-directory writer for plan-only runs.

Stages the seven plan-only artifacts under a sibling temp directory and
atomically renames it onto ``<out_dir>``:

1. ``scenario.yaml`` (verbatim source bytes)
2. ``replay.json``
3. ``manifest.initial.json``
4. ``manifest.current.json``
5. ``journal.jsonl``
6. ``validation.json``
7. ``.chaos-librarian-run`` (sentinel, written LAST inside staging)

The single ``Path.replace`` makes publication atomic on POSIX and macOS:
observers see either nothing or every file. Any failure during staging
triggers ``shutil.rmtree`` so a partial fixture cannot persist.

JSON canonicalization is centralized in ``_emit_json`` /  ``_emit_jsonl``
so every Sprint 3 artifact serializes the same way: ``indent=2``,
``by_alias=True``, ``exclude_none=True``, trailing ``"\n"``. This is what
makes plan-only output bit-identical.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine.plan import PlanArtifacts


def write_fixture(
    out_dir: Path,
    artifacts: PlanArtifacts,
    scenario_yaml_bytes: bytes,
) -> None:
    """Persist a PlanArtifacts result to disk atomically.

    Args:
        out_dir: Target directory. MUST NOT already exist; the function
            creates it (via atomic rename from staging) and refuses to
            overwrite.
        artifacts: The result of ``run_plan``.
        scenario_yaml_bytes: Verbatim source YAML bytes, written to
            ``scenario.yaml`` without modification.

    Raises:
        FileExistsError: If ``out_dir`` already exists.
    """
    if out_dir.exists():
        raise FileExistsError(f"refusing to write into existing directory: {out_dir}")

    staging = Path(tempfile.mkdtemp(prefix=".chaos-librarian-staging-", dir=out_dir.parent))
    try:
        (staging / "scenario.yaml").write_bytes(scenario_yaml_bytes)
        _emit_json(artifacts.replay_bundle, staging / "replay.json")
        _emit_json(artifacts.initial_manifest, staging / "manifest.initial.json")
        _emit_json(artifacts.current_manifest, staging / "manifest.current.json")
        _emit_jsonl(artifacts.journal, staging / "journal.jsonl")
        _emit_json(artifacts.validation_report, staging / "validation.json")
        _emit_sentinel(staging, artifacts.sentinel)
        staging.replace(out_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _emit_sentinel(out_dir: Path, sentinel: RunSentinel) -> None:
    """Write the sentinel into the staging directory last."""
    target = out_dir / ".chaos-librarian-run"
    payload = sentinel.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"
    target.write_text(payload)


def _emit_json(model: BaseModel, target: Path) -> None:
    """Write one Pydantic model as canonical JSON with trailing newline."""
    payload = model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"
    target.write_text(payload)


def _emit_jsonl(entries: Iterable[JournalEntry], target: Path) -> None:
    """Write each entry as one canonical-JSON line; empty iter writes an empty file."""
    lines: list[str] = []
    for entry in entries:
        lines.append(entry.model_dump_json(by_alias=True, exclude_none=True))
    if not lines:
        target.write_text("")
        return
    target.write_text("\n".join(lines) + "\n")
