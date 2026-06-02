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
from chaos_librarian.validation.scenario_io import (
    LineIndex,
    ScenarioLoadError,
    parse_scenario_bytes,
)

_SCENARIO_CACHE_KEY = "scenario"


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

        The cached Scenario is shared across every consumer that holds the
        same RunInput (shape pass, ``run_plan``, ``replay_plan_bundle``,
        ``materialize_scenario``). Mutating it would desync the engine's
        output from the bytes the replay bundle records. The Scenario
        subtree is ``frozen=True`` with tuple collection fields so
        attribute reassignment and list mutators both raise.

        Raises ``pydantic.ValidationError`` on shape-invalid input. The
        shape pass catches this and converts to structured issues; callers
        downstream of a passing validation report may assume access
        succeeds.
        """
        return Scenario.model_validate(self.raw_data)

    def prime_scenario_cache(self, parsed: Scenario) -> None:
        """Authoritatively populate the ``scenario`` cache from a fresh parse.

        The shape pass parses ``raw_data`` directly and calls this so the
        cache always reflects the most recent validation, even if a caller
        warmed it earlier by reading ``scenario`` and then mutated
        ``raw_data``. Writes to ``__dict__`` to bypass the frozen
        dataclass setattr block.
        """
        self.__dict__[_SCENARIO_CACHE_KEY] = parsed

    def invalidate_scenario_cache(self) -> None:
        """Drop any cached Scenario so the next ``scenario`` access re-parses.

        The shape pass calls this on validation failure to ensure a stale
        cache from pre-validation access cannot mask a shape error in
        the current ``raw_data``.
        """
        self.__dict__.pop(_SCENARIO_CACHE_KEY, None)


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
