"""Single-read scenario input bound to its bytes.

``RunInput`` is the unit of work threaded through the validation pipeline
and the plan-only engine. Every step that needs the parsed YAML, the raw
bytes, or the content hash refers back to the *same* immutable record —
so the report, the replay bundle, and the published ``scenario.yaml`` can
never describe drift between three reads of the same path.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chaos_librarian.scenario_io import LineIndex, ScenarioLoadError, parse_scenario_bytes


@dataclass(frozen=True)
class RunInput:
    """One immutable read of a scenario source."""

    path: Path
    raw_bytes: bytes
    content_hash: str
    raw_data: Any
    line_index: LineIndex


def prepare_run_input(path: Path) -> RunInput:
    """Read, hash, and parse a scenario file exactly once.

    Raises:
        ScenarioLoadError: if the file cannot be read or is not valid YAML.
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ScenarioLoadError(f"cannot read {path}: {exc}", line=None, column=None) from exc
    return _from_bytes(path=path, raw_bytes=raw_bytes)


def prepare_run_input_from_bytes(*, raw_bytes: bytes, source_label: str) -> RunInput:
    """Bind a RunInput to in-memory bytes (e.g. the scenario field of a replay bundle)."""
    return _from_bytes(path=Path(source_label), raw_bytes=raw_bytes)


def _from_bytes(*, path: Path, raw_bytes: bytes) -> RunInput:
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    raw_data, line_index = parse_scenario_bytes(raw_bytes, source=path)
    return RunInput(
        path=path,
        raw_bytes=raw_bytes,
        content_hash=content_hash,
        raw_data=raw_data,
        line_index=line_index,
    )
