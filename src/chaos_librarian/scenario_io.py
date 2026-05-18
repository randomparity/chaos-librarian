"""YAML loader with per-node line/column tracking.

Uses ``ruamel.yaml`` round-trip mode for position info, then walks the
parsed tree once to build a path-tuple → (line, column) index. Returns a
plain ``dict`` / ``list`` tree so downstream passes never depend on
ruamel-specific types.

Lines are exposed 1-based (editor convention) even though ruamel reports
0-based internally.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from chaos_librarian.errors import ChaosLibrarianError

_PathPart = str | int
_PathTuple = tuple[_PathPart, ...]


class ScenarioLoadError(ChaosLibrarianError):
    """Raised when the YAML file cannot be parsed.

    Attributes:
        line: 1-based line of the failure if ruamel reported one, else None.
        column: 0-based column of the failure if ruamel reported one, else None.
    """

    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


@dataclass(frozen=True)
class LineIndex:
    """Maps path tuples to ``(line, column)`` for downstream issue reporting."""

    entries: Mapping[_PathTuple, tuple[int, int]] = field(default_factory=dict)

    def lookup(self, loc: _PathTuple) -> tuple[int, int] | None:
        return self.entries.get(loc)


def load_scenario(path: Path) -> tuple[Any, LineIndex, bytes, str]:
    """Read, parse, and hash a YAML scenario file in one pass.

    Args:
        path: Absolute or relative path to a YAML file.

    Returns:
        ``(raw_data, line_index, raw_bytes, content_hash)``. ``raw_data`` is
        a plain Python tree (dict / list / scalars); ``raw_bytes`` is the
        exact source for byte-binding (replay bundle, content hash);
        ``content_hash`` is the sha256 hex digest of ``raw_bytes``. The
        caller is responsible for the top-level-shape check (see
        ``validation.pipeline``).

    Raises:
        ScenarioLoadError: On any YAMLError, missing file, or unreadable file.
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as e:
        raise ScenarioLoadError(f"cannot read {path}: {e}", line=None, column=None) from e

    raw_data, line_index = parse_scenario_bytes(raw_bytes, source=path)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    return raw_data, line_index, raw_bytes, content_hash


def parse_scenario_bytes(raw_bytes: bytes, *, source: Path) -> tuple[Any, LineIndex]:
    """Parse pre-read YAML bytes into ``(raw_data, line_index)``.

    Shared by ``load_scenario`` (path-based) and
    ``chaos_librarian.validation.input.prepare_run_input_from_bytes``
    (bundle-replay path). ``source`` is used only in error messages.

    Raises:
        ScenarioLoadError: If ruamel rejects the bytes as malformed YAML.
    """
    yaml = YAML(typ="rt")
    try:
        loaded = yaml.load(io.BytesIO(raw_bytes))
    except YAMLError as e:
        line, column = _yaml_error_position(e)
        raise ScenarioLoadError(f"YAML parse error in {source}: {e}", line, column) from e

    index_data: dict[_PathTuple, tuple[int, int]] = {}
    plain = _walk(loaded, path_so_far=(), index=index_data)
    return plain, LineIndex(entries=index_data)


def _walk(
    node: Any,
    path_so_far: _PathTuple,
    index: dict[_PathTuple, tuple[int, int]],
) -> Any:
    """Recursively convert ruamel containers to plain dict/list, recording positions."""
    if isinstance(node, CommentedMap):
        return _walk_map(node, path_so_far, index)
    if isinstance(node, CommentedSeq):
        return _walk_seq(node, path_so_far, index)
    return node


def _walk_map(
    node: CommentedMap,
    path_so_far: _PathTuple,
    index: dict[_PathTuple, tuple[int, int]],
) -> dict[str, Any]:
    """Convert a CommentedMap to a plain dict, recording each key's position."""
    result: dict[str, Any] = {}
    lc_data = getattr(node, "lc", None)
    for key, value in node.items():
        child_path = (*path_so_far, key)
        if lc_data is not None and lc_data.data is not None and key in lc_data.data:
            # lc.data[key] is (key_line, key_col, value_line, value_col), 0-based.
            key_line, key_col, *_ = lc_data.data[key]
            index[child_path] = (key_line + 1, key_col)
        result[key] = _walk(value, child_path, index)
    return result


def _walk_seq(
    node: CommentedSeq,
    path_so_far: _PathTuple,
    index: dict[_PathTuple, tuple[int, int]],
) -> list[Any]:
    """Convert a CommentedSeq to a plain list, recording each item's position."""
    result: list[Any] = []
    lc_data = getattr(node, "lc", None)
    for idx, value in enumerate(node):
        child_path = (*path_so_far, idx)
        position = _seq_item_position(lc_data, idx)
        if position is not None:
            index[child_path] = position
        result.append(_walk(value, child_path, index))
    return result


def _seq_item_position(
    lc_data: Any,
    idx: int,
) -> tuple[int, int] | None:
    """Return 1-based ``(line, column)`` for sequence item ``idx``, if known.

    ``ruamel`` reports positions through ``CommentedSeq.lc.item``; for
    empty sequences or subclasses without an ``lc`` attribute the call
    raises. We treat any of those cases as "position unknown" — the
    caller falls back to the parent path's position when looking up.
    """
    if lc_data is None:
        return None
    try:
        line, col = lc_data.item(idx)
    except (AttributeError, KeyError, TypeError):
        return None
    return line + 1, col


def _yaml_error_position(error: YAMLError) -> tuple[int | None, int | None]:
    """Extract 1-based line and 0-based column from a YAMLError if available."""
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    if mark is None:
        return None, None
    return mark.line + 1, mark.column
