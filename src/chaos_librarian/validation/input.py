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
from functools import cached_property
from pathlib import Path
from typing import Any

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.scenario_io import LineIndex, ScenarioLoadError, parse_scenario_bytes


@dataclass(frozen=True)
class RunInput:
    """One immutable read of a scenario source."""

    path: Path
    raw_bytes: bytes
    content_hash: str
    raw_data: Any
    line_index: LineIndex

    @cached_property
    def scenario(self) -> Scenario:
        """Parsed Scenario, computed once per RunInput.

        First access invokes ``Scenario.model_validate`` and caches the
        result in the instance ``__dict__`` (cached_property writes there
        directly, so the frozen dataclass setattr block is bypassed).
        Subsequent accesses return the same object identity.

        Raises ``pydantic.ValidationError`` on shape-invalid input; the
        validation pipeline's shape pass catches it and converts to
        structured issues. Callers downstream of a passing validation
        report may assume the access succeeds.
        """
        return Scenario.model_validate(self.raw_data)


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
