"""Fixture-vs-fixture diff for ``replay`` artifact divergence detection.

``compare_fixtures(left_dir, right_dir)`` walks both directories
recursively, treats the sentinel file's ``created_at`` field as
ignorable (plan-only omits it anyway), and reports per-file
divergences. ``replay`` (Task 13) wraps this into exit-6 structured
output when bytes don't match.

Zero new runtime dependencies.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import TypeAdapter

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.engine.journal_io import serialize_journal_bytes

_DiffKind = Literal["byte_diff", "missing_in_left", "missing_in_right"]
_TEXT_SUFFIXES = frozenset({".json", ".jsonl", ".yaml", ".yml"})
_SENTINEL_BASENAME = ".chaos-librarian-run"
_PREVIEW_LIMIT = 80
_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)
_RUN_REPLAY_COMPARE_KEYS = frozenset(
    {
        "scenario",
        "run_id",
        "resolved_seed",
        "applied_events",
        "journal_digest",
        "execution_mode",
        "content_sources",
    }
)


@dataclass(frozen=True)
class FixtureFileDiff:
    """A single per-file divergence between two fixture directories.

    Attributes:
        path: Relative path inside the fixture root (POSIX separators).
        kind: Whether the file differs in bytes or is missing from one side.
        left_bytes: Size of the left file in bytes; ``None`` if absent.
        right_bytes: Size of the right file in bytes; ``None`` if absent.
        first_diff_line: 1-indexed line at which text-like files first diverge.
        preview_left: Short slice of the differing line from the left file.
        preview_right: Short slice of the differing line from the right file.
    """

    path: str
    kind: _DiffKind
    left_bytes: int | None
    right_bytes: int | None
    first_diff_line: int | None
    preview_left: str | None
    preview_right: str | None


@dataclass(frozen=True)
class FixtureDiff:
    """Result of comparing two fixture directories.

    Attributes:
        left_dir: Root of the left-hand fixture.
        right_dir: Root of the right-hand fixture.
        files: Per-file divergences in stable lexicographic order; empty when
            the fixtures are byte-identical.
    """

    left_dir: Path
    right_dir: Path
    files: tuple[FixtureFileDiff, ...]

    def is_clean(self) -> bool:
        """Return ``True`` when no per-file divergences were detected."""
        return not self.files


def compare_fixtures(left_dir: Path, right_dir: Path) -> FixtureDiff:
    """Return per-file divergences between two fixture directories.

    Walks both roots with ``Path.rglob('*')`` and compares each file by
    raw bytes. Text-like files (``.json`` / ``.jsonl`` / ``.yaml`` /
    ``.yml`` / the ``.chaos-librarian-run`` sentinel) get a first-diff
    line index plus short previews; binary files report byte counts only.

    Args:
        left_dir: Root of the left-hand fixture directory.
        right_dir: Root of the right-hand fixture directory.

    Returns:
        A :class:`FixtureDiff` whose ``files`` tuple is empty when every
        file is present in both directories with identical bytes.
    """
    left_files = _collect(left_dir)
    right_files = _collect(right_dir)
    diffs: list[FixtureFileDiff] = []
    for rel in sorted(left_files | right_files):
        in_left = rel in left_files
        in_right = rel in right_files
        if not in_left:
            right_path = right_dir / rel
            diffs.append(
                FixtureFileDiff(
                    path=rel,
                    kind="missing_in_left",
                    left_bytes=None,
                    right_bytes=right_path.stat().st_size,
                    first_diff_line=None,
                    preview_left=None,
                    preview_right=None,
                )
            )
            continue
        if not in_right:
            left_path = left_dir / rel
            diffs.append(
                FixtureFileDiff(
                    path=rel,
                    kind="missing_in_right",
                    left_bytes=left_path.stat().st_size,
                    right_bytes=None,
                    first_diff_line=None,
                    preview_left=None,
                    preview_right=None,
                )
            )
            continue
        left_path = left_dir / rel
        right_path = right_dir / rel
        left_bytes = left_path.read_bytes()
        right_bytes = right_path.read_bytes()
        if left_bytes == right_bytes:
            continue
        diffs.append(_byte_diff_entry(rel, left_bytes, right_bytes))
    return FixtureDiff(left_dir=left_dir, right_dir=right_dir, files=tuple(diffs))


def compare_run_replay(left_dir: Path, right_dir: Path) -> FixtureDiff:
    """Compare run replay outputs while ignoring wall-clock-only volatility."""
    diffs: list[FixtureFileDiff] = []
    _compare_json(
        diffs,
        left_dir,
        right_dir,
        "manifest.current.json",
        normalizer=lambda data: data,
    )
    _compare_json(
        diffs,
        left_dir,
        right_dir,
        "replay.json",
        normalizer=_normalize_replay_bundle_for_run_replay,
    )
    _compare_journal(diffs, left_dir, right_dir)
    _compare_json(
        diffs,
        left_dir,
        right_dir,
        "materialization.json",
        normalizer=_normalize_materialization_for_run_replay,
    )
    _compare_tree_bytes(diffs, left_dir, right_dir, "library")
    _compare_tree_bytes(diffs, left_dir, right_dir, "reports")
    return FixtureDiff(left_dir=left_dir, right_dir=right_dir, files=tuple(diffs))


def _collect(root: Path) -> set[str]:
    """Return the set of file paths under ``root`` as POSIX-relative strings.

    Directories are excluded; only regular files contribute. Relative paths
    use ``Path.as_posix()`` so comparisons stay portable across platforms.
    """
    rels: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rels.add(path.relative_to(root).as_posix())
    return rels


def _compare_json(
    diffs: list[FixtureFileDiff],
    left_dir: Path,
    right_dir: Path,
    rel: str,
    *,
    normalizer: Callable[[object], object],
) -> None:
    left = left_dir / rel
    right = right_dir / rel
    if not _record_missing(diffs, left, right, rel):
        return
    left_blob = _canonical_compare_json(normalizer(json.loads(left.read_text(encoding="utf-8"))))
    right_blob = _canonical_compare_json(normalizer(json.loads(right.read_text(encoding="utf-8"))))
    if left_blob != right_blob:
        diffs.append(_plain_byte_diff_entry(rel, left_blob, right_blob))


def _compare_journal(diffs: list[FixtureFileDiff], left_dir: Path, right_dir: Path) -> None:
    rel = "journal.jsonl"
    left = left_dir / rel
    right = right_dir / rel
    if not _record_missing(diffs, left, right, rel):
        return
    left_blob = _normalized_journal_bytes(left)
    right_blob = _normalized_journal_bytes(right)
    if left_blob != right_blob:
        diffs.append(_plain_byte_diff_entry(rel, left_blob, right_blob))


def _compare_tree_bytes(
    diffs: list[FixtureFileDiff],
    left_dir: Path,
    right_dir: Path,
    rel_root: str,
) -> None:
    left_files = _collect(left_dir / rel_root)
    right_files = _collect(right_dir / rel_root)
    for rel in sorted(left_files | right_files):
        fixture_rel = f"{rel_root}/{rel}"
        left = left_dir / fixture_rel
        right = right_dir / fixture_rel
        if not _record_missing(diffs, left, right, fixture_rel):
            continue
        left_blob = left.read_bytes()
        right_blob = right.read_bytes()
        if left_blob != right_blob:
            diffs.append(_plain_byte_diff_entry(fixture_rel, left_blob, right_blob))


def _normalize_materialization_for_run_replay(data: object) -> dict[str, object]:
    data_obj = _str_keyed_dict(data)
    if data_obj is None:
        data_obj = {}
    return {
        "outcome": data_obj.get("outcome"),
        "execution_mode": data_obj.get("execution_mode"),
        "content_sources": _required_list_or_missing(data_obj, "content_sources"),
        "materialized": _list_or_empty(data_obj.get("materialized")),
        "failures": _list_or_empty(data_obj.get("failures")),
        "filesystem_actions": _normalize_action_list(data_obj.get("filesystem_actions")),
        "media_actions": _normalize_action_list(data_obj.get("media_actions")),
        "corruption_actions": _normalize_action_list(data_obj.get("corruption_actions")),
        "oracle_hash_actions": _normalize_action_list(data_obj.get("oracle_hash_actions")),
    }


def _normalize_replay_bundle_for_run_replay(data: object) -> dict[str, object]:
    data_obj = _str_keyed_dict(data)
    if data_obj is None:
        data_obj = {}
    return {key: data_obj.get(key) for key in _RUN_REPLAY_COMPARE_KEYS}


def _list_or_empty(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return cast("list[object]", value)


def _required_list_or_missing(data: dict[str, object], field: str) -> object:
    if field not in data:
        return {"missing_required_field": field}
    value = data[field]
    if isinstance(value, list):
        return cast("list[object]", value)
    return value


def _normalize_action_list(value: object) -> list[object]:
    actions = _list_or_empty(value)
    normalized: list[object] = []
    for action in actions:
        action_data = _str_keyed_dict(action)
        if action_data is None:
            normalized.append(action)
            continue
        normalized.append(
            {
                field: field_value
                for field, field_value in action_data.items()
                if field != "duration_ns"
            }
        )
    return normalized


def _str_keyed_dict(data: object) -> dict[str, object] | None:
    if not isinstance(data, dict):
        return None
    return cast("dict[str, object]", data)


def _normalized_journal_bytes(path: Path) -> bytes:
    entries = [
        _JOURNAL_ADAPTER.validate_json(line).model_copy(update={"wall_clock_time": None})
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return serialize_journal_bytes(entries)


def _canonical_compare_json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _record_missing(
    diffs: list[FixtureFileDiff],
    left: Path,
    right: Path,
    rel: str,
) -> bool:
    if left.exists() and right.exists():
        return True
    if not left.exists():
        diffs.append(
            FixtureFileDiff(
                path=rel,
                kind="missing_in_left",
                left_bytes=None,
                right_bytes=right.stat().st_size if right.exists() else None,
                first_diff_line=None,
                preview_left=None,
                preview_right=None,
            )
        )
        return False
    diffs.append(
        FixtureFileDiff(
            path=rel,
            kind="missing_in_right",
            left_bytes=left.stat().st_size,
            right_bytes=None,
            first_diff_line=None,
            preview_left=None,
            preview_right=None,
        )
    )
    return False


def _is_text_like(rel: str) -> bool:
    """Return ``True`` when the file should get a line-level diff preview.

    Text-like files are JSON, JSON Lines, YAML, or the
    ``.chaos-librarian-run`` sentinel; everything else is treated as binary.
    """
    if Path(rel).name == _SENTINEL_BASENAME:
        return True
    return Path(rel).suffix.lower() in _TEXT_SUFFIXES


def _byte_diff_entry(rel: str, left: bytes, right: bytes) -> FixtureFileDiff:
    """Build a ``byte_diff`` entry, populating line info for text-like files."""
    if _is_text_like(rel):
        first_diff_line, preview_left, preview_right = _line_diff(left, right)
    else:
        first_diff_line, preview_left, preview_right = None, None, None
    return FixtureFileDiff(
        path=rel,
        kind="byte_diff",
        left_bytes=len(left),
        right_bytes=len(right),
        first_diff_line=first_diff_line,
        preview_left=preview_left,
        preview_right=preview_right,
    )


def _plain_byte_diff_entry(rel: str, left: bytes, right: bytes) -> FixtureFileDiff:
    return FixtureFileDiff(
        path=rel,
        kind="byte_diff",
        left_bytes=len(left),
        right_bytes=len(right),
        first_diff_line=None,
        preview_left=None,
        preview_right=None,
    )


def _line_diff(left: bytes, right: bytes) -> tuple[int | None, str | None, str | None]:
    """Find the first differing line between two text-like blobs.

    Returns a 1-indexed line number together with truncated previews of the
    differing line from each side. When the shared prefix is identical but
    one side has more lines, the line index points at the first extra line
    and the missing side's preview is ``None``.
    """
    left_lines = left.decode("utf-8", errors="replace").splitlines()
    right_lines = right.decode("utf-8", errors="replace").splitlines()
    for idx, (l_line, r_line) in enumerate(zip(left_lines, right_lines, strict=False), start=1):
        if l_line != r_line:
            return idx, l_line[:_PREVIEW_LIMIT], r_line[:_PREVIEW_LIMIT]
    if len(left_lines) != len(right_lines):
        shorter = min(len(left_lines), len(right_lines))
        idx = shorter + 1
        l_preview = left_lines[idx - 1][:_PREVIEW_LIMIT] if idx - 1 < len(left_lines) else None
        r_preview = right_lines[idx - 1][:_PREVIEW_LIMIT] if idx - 1 < len(right_lines) else None
        return idx, l_preview, r_preview
    return None, None, None
