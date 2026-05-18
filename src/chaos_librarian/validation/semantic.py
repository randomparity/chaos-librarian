"""Semantic-validation pass.

Rules are plain functions with signature ``(raw, line_index, collector) -> None``.
They are registered in ``_RULES`` and run in declared order. Each rule
guards its own preconditions: Pydantic owns "the field exists and is the
right type"; rules only check semantics on top of well-shaped sub-trees.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from chaos_librarian.clock import DurationParseError, parse_duration
from chaos_librarian.contract.paths import PathContainmentError, resolve_under_library
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation import codes

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


_Loc = tuple[str | int, ...]
_RawMapping = Mapping[str, object]
_Rule = Callable[[_RawMapping, "LineIndex", "IssueCollector"], None]


def _as_mapping(node: object) -> _RawMapping | None:
    """Narrow an ``object`` to ``Mapping[str, object]`` for safe ``.get`` calls.

    Pydantic owns shape-level enforcement (a non-mapping where a mapping is
    expected fires E_FIELD_TYPE in the shape pass). Returning None here is
    the rule's way of saying "skip this malformed sub-tree".

    The ``cast`` is needed because ``isinstance`` against a generic alias is
    erased at runtime; we trust the YAML loader to produce string-keyed maps.
    """
    if isinstance(node, Mapping):
        return cast("_RawMapping", node)
    return None


def _as_list(node: object) -> list[object] | None:
    """Narrow an ``object`` to ``list[object]``; mirror of ``_as_mapping``."""
    if isinstance(node, list):
        return cast("list[object]", node)
    return None


def run_semantic_pass(
    raw_data: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Apply every registered rule in declared order."""
    for rule in _RULES:
        rule(raw_data, line_index, collector)


# ---- Rule 1: E_ID_DUPLICATE -----------------------------------------------


def _rule_id_duplicate(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject duplicate IDs per the namespace table in the Sprint 1 spec.

    Global namespaces (across the whole scenario): variant_id, bundle_id,
    asset_id. Top-level namespaces: root_id, work_id, timeline_id.
    """
    _check_top_level_dups(
        raw=raw,
        namespace="root_id",
        path_parts=("library", "roots"),
        line_index=line_index,
        collector=collector,
    )
    _check_top_level_dups(
        raw=raw,
        namespace="work_id",
        path_parts=("works",),
        line_index=line_index,
        collector=collector,
    )
    _check_top_level_dups(
        raw=raw,
        namespace="timeline_id",
        path_parts=("timeline",),
        line_index=line_index,
        collector=collector,
    )

    seen: dict[str, dict[str, _Loc]] = {
        "variant_id": {},
        "bundle_id": {},
        "asset_id": {},
    }
    for namespace, value, loc in _iter_global_namespaces(raw):
        _record_or_report(
            namespace=namespace,
            value=value,
            loc=loc,
            seen=seen[namespace],
            line_index=line_index,
            collector=collector,
        )


def _iter_global_namespaces(
    raw: Mapping[str, object],
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``(namespace, id_value, loc)`` for every variant/bundle/asset id.

    Walks ``works[*].variants[*].bundle.assets[*]`` and skips any sub-tree
    whose shape Pydantic would have rejected; shape errors are surfaced by
    the shape pass, not here.
    """
    works = _as_list(raw.get("works"))
    if works is None:
        return
    for w_idx, work_obj in enumerate(works):
        work = _as_mapping(work_obj)
        if work is None:
            continue
        variants = _as_list(work.get("variants"))
        if variants is None:
            continue
        for v_idx, variant in enumerate(variants):
            yield from _iter_variant(variant, w_idx=w_idx, v_idx=v_idx)


def _iter_variant(
    variant_obj: object,
    *,
    w_idx: int,
    v_idx: int,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ids for one variant and the bundle/assets nested below it."""
    variant = _as_mapping(variant_obj)
    if variant is None:
        return
    v_id = variant.get("id")
    if isinstance(v_id, str):
        yield "variant_id", v_id, ("works", w_idx, "variants", v_idx, "id")
    bundle = _as_mapping(variant.get("bundle"))
    if bundle is None:
        return
    b_id = bundle.get("id")
    bundle_path: _Loc = ("works", w_idx, "variants", v_idx, "bundle")
    if isinstance(b_id, str):
        yield "bundle_id", b_id, (*bundle_path, "id")
    yield from _iter_bundle_assets(bundle.get("assets"), bundle_path=bundle_path)


def _iter_bundle_assets(
    assets_obj: object,
    *,
    bundle_path: _Loc,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``asset_id`` triples for each well-shaped asset under a bundle."""
    assets = _as_list(assets_obj)
    if assets is None:
        return
    for a_idx, asset_obj in enumerate(assets):
        asset = _as_mapping(asset_obj)
        if asset is None:
            continue
        a_id = asset.get("id")
        if isinstance(a_id, str):
            yield "asset_id", a_id, (*bundle_path, "assets", a_idx, "id")


def _check_top_level_dups(
    *,
    raw: Mapping[str, object],
    namespace: str,
    path_parts: tuple[str, ...],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Top-level duplicate-id check: walk one list field and report collisions."""
    node: object = raw
    for part in path_parts:
        parent = _as_mapping(node)
        if parent is None:
            return
        node = parent.get(part)
    items = _as_list(node)
    if items is None:
        return
    seen: dict[str, _Loc] = {}
    for idx, item_obj in enumerate(items):
        item = _as_mapping(item_obj)
        if item is None:
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str):
            continue
        loc = (*path_parts, idx, "id")
        _record_or_report(
            namespace=namespace,
            value=item_id,
            loc=loc,
            seen=seen,
            line_index=line_index,
            collector=collector,
        )


def _record_or_report(
    *,
    namespace: str,
    value: str,
    loc: _Loc,
    seen: dict[str, _Loc],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    if value in seen:
        first_path = codes.format_jsonpath(seen[value])
        collector.add(
            code=codes.E_ID_DUPLICATE,
            severity=ValidationSeverity.ERROR,
            message=f"duplicate {namespace} {value!r} (first defined at {first_path})",
            loc=loc,
            line_index=line_index,
        )
    else:
        seen[value] = loc


# ---- Rule 2: E_PATH_DUPLICATE ---------------------------------------------


def _rule_path_duplicate(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Warn on two library roots with the same ``path`` (distinct IDs).

    WARNING severity — does not flip ``report.ok``. Authors who genuinely
    want to alias a directory under two ID namespaces can ignore it.
    """
    library = _as_mapping(raw.get("library"))
    if library is None:
        return
    roots = _as_list(library.get("roots"))
    if roots is None:
        return
    seen: dict[str, _Loc] = {}
    for idx, root_obj in enumerate(roots):
        root = _as_mapping(root_obj)
        if root is None:
            continue
        path = root.get("path")
        if not isinstance(path, str):
            continue
        loc: _Loc = ("library", "roots", idx, "path")
        if path in seen:
            first_path = codes.format_jsonpath(seen[path])
            collector.add(
                code=codes.E_PATH_DUPLICATE,
                severity=ValidationSeverity.WARNING,
                message=f"root path {path!r} already used at {first_path}",
                loc=loc,
                line_index=line_index,
            )
        else:
            seen[path] = loc


# ---- Rule 3: E_DURATION_SYNTAX --------------------------------------------


def _check_duration(
    *,
    raw_str: str,
    loc: _Loc,
    field_label: str,
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Parse one duration string; on failure, emit one E_DURATION_SYNTAX issue.

    Extracted so ``_rule_duration_syntax`` stays under the 8-branch CC limit:
    the try/except plus the issue construction are the costly bit, and they
    are identical for both fields we check.
    """
    try:
        parse_duration(raw_str)
    except DurationParseError as e:
        collector.add(
            code=codes.E_DURATION_SYNTAX,
            severity=ValidationSeverity.ERROR,
            message=f"invalid {field_label} {raw_str!r}: {e.reason}",
            loc=loc,
            line_index=line_index,
        )


def _rule_duration_syntax(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject unparseable duration strings on timeline events.

    Fields checked: ``timeline[*].at`` (every event) and
    ``slow_copy_start.duration`` (only when ``action == "slow_copy_start"``).
    """
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        at = event.get("at")
        if isinstance(at, str):
            _check_duration(
                raw_str=at,
                loc=("timeline", idx, "at"),
                field_label="at duration",
                line_index=line_index,
                collector=collector,
            )
        if event.get("action") == "slow_copy_start":
            duration = event.get("duration")
            if isinstance(duration, str):
                _check_duration(
                    raw_str=duration,
                    loc=("timeline", idx, "duration"),
                    field_label="duration",
                    line_index=line_index,
                    collector=collector,
                )


# ---- Rule 4: E_TARGET_UNKNOWN ---------------------------------------------


def _rule_target_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject timeline events whose ``target:`` is not a defined asset id.

    Reuses ``_iter_global_namespaces`` (already walks works→variants→
    bundle→assets for Rule 1) and filters to the ``asset_id`` namespace —
    a fresh walker here would duplicate the same shape-skipping logic.
    Events with no string ``target`` (e.g. ``slow_copy_commit``) are
    skipped: Pydantic's shape pass owns "the field must exist."
    """
    asset_ids = {
        value for namespace, value, _ in _iter_global_namespaces(raw) if namespace == "asset_id"
    }
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        target = event.get("target")
        if not isinstance(target, str):
            continue
        if target not in asset_ids:
            collector.add(
                code=codes.E_TARGET_UNKNOWN,
                severity=ValidationSeverity.ERROR,
                message=f"target asset {target!r} is not defined in any bundle",
                loc=("timeline", idx, "target"),
                line_index=line_index,
            )


# ---- Rules 5a + 5b: slow-copy pairing and timing --------------------------


def _index_starts_and_commits(
    timeline: list[object],
) -> tuple[dict[str, tuple[int, _RawMapping]], list[tuple[int, _RawMapping]]]:
    """Split a timeline into ``slow_copy_start`` index and commit list.

    Extracted from ``_rule_slow_copy_unpaired`` so the rule body stays under
    the 8-branch CC limit. Returns ``(starts_by_id, commits)`` where each
    entry preserves the original timeline index for error ``loc`` reporting.
    """
    starts: dict[str, tuple[int, _RawMapping]] = {}
    commits: list[tuple[int, _RawMapping]] = []
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        action = event.get("action")
        ev_id = event.get("id")
        if action == "slow_copy_start" and isinstance(ev_id, str):
            starts[ev_id] = (idx, event)
        elif action == "slow_copy_commit":
            commits.append((idx, event))
    return starts, commits


def _report_orphan_starts(
    *,
    commits_per_start: dict[str, int],
    starts: dict[str, tuple[int, _RawMapping]],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Emit E_SLOW_COPY_UNPAIRED for any start with zero or >1 matching commits."""
    for sid, count in commits_per_start.items():
        s_idx, _ = starts[sid]
        if count == 0:
            collector.add(
                code=codes.E_SLOW_COPY_UNPAIRED,
                severity=ValidationSeverity.ERROR,
                message=f"slow_copy_start {sid!r} has no matching slow_copy_commit",
                loc=("timeline", s_idx, "id"),
                line_index=line_index,
            )
        elif count > 1:
            collector.add(
                code=codes.E_SLOW_COPY_UNPAIRED,
                severity=ValidationSeverity.ERROR,
                message=f"slow_copy_start {sid!r} has {count} matching commits (expected 1)",
                loc=("timeline", s_idx, "id"),
                line_index=line_index,
            )


def _rule_slow_copy_unpaired(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """5a: structural pairing of slow_copy_start <-> slow_copy_commit."""
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    starts, commits = _index_starts_and_commits(timeline)
    commits_per_start: dict[str, int] = {sid: 0 for sid in starts}
    for c_idx, commit in commits:
        ref = commit.get("for")
        if not isinstance(ref, str):
            continue  # Pydantic owns shape
        if ref not in starts:
            collector.add(
                code=codes.E_SLOW_COPY_UNPAIRED,
                severity=ValidationSeverity.ERROR,
                message=f"slow_copy_commit references unknown slow_copy_start {ref!r}",
                loc=("timeline", c_idx, "for"),
                line_index=line_index,
            )
            continue
        commits_per_start[ref] += 1
    _report_orphan_starts(
        commits_per_start=commits_per_start,
        starts=starts,
        line_index=line_index,
        collector=collector,
    )


def _index_starts(timeline: list[object]) -> dict[str, tuple[int, _RawMapping]]:
    """Index ``slow_copy_start`` events by id; helper for Rule 5b."""
    starts: dict[str, tuple[int, _RawMapping]] = {}
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None or event.get("action") != "slow_copy_start":
            continue
        sid = event.get("id")
        if isinstance(sid, str):
            starts[sid] = (idx, event)
    return starts


def _check_pair_timing(
    *,
    c_idx: int,
    commit: _RawMapping,
    start: _RawMapping,
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Validate one matched pair's ``commit.at == start.at + start.duration``.

    Skips silently when any of the three durations fail to parse — Rule 3
    has already flagged that case, and double-reporting would be noise.
    """
    start_at = start.get("at")
    start_dur = start.get("duration")
    commit_at = commit.get("at")
    if not isinstance(start_at, str):
        return  # Rule 3 / Pydantic flagged
    if not isinstance(start_dur, str) or not isinstance(commit_at, str):
        return  # Rule 3 / Pydantic flagged
    try:
        start_at_ns = parse_duration(start_at)
        start_dur_ns = parse_duration(start_dur)
        commit_at_ns = parse_duration(commit_at)
    except DurationParseError:
        return  # Rule 3 flagged
    expected = start_at_ns + start_dur_ns
    if commit_at_ns != expected:
        collector.add(
            code=codes.E_SLOW_COPY_TIMING,
            severity=ValidationSeverity.ERROR,
            message=(
                f"slow_copy_commit.at {commit_at!r} != "
                f"start.at {start_at!r} + duration {start_dur!r}"
            ),
            loc=("timeline", c_idx, "at"),
            line_index=line_index,
        )


def _rule_slow_copy_timing(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """5b: strict equality ``commit.at == start.at + start.duration``.

    Preconditions: durations on both events parse (Rule 3 already flagged
    otherwise) AND structural pairing holds (Rule 5a already flagged
    orphans). Skipping here prevents double-reporting.
    """
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    starts = _index_starts(timeline)
    for c_idx, event_obj in enumerate(timeline):
        commit = _as_mapping(event_obj)
        if commit is None or commit.get("action") != "slow_copy_commit":
            continue
        ref = commit.get("for")
        if not isinstance(ref, str) or ref not in starts:
            continue  # Rule 5a flagged orphan
        _, start = starts[ref]
        _check_pair_timing(
            c_idx=c_idx,
            commit=commit,
            start=start,
            line_index=line_index,
            collector=collector,
        )


# ---- Rule 6: E_PATH_CONTAINMENT -------------------------------------------


_SYNTHETIC_LIBRARY_ROOT: Path = Path("/__chaos_librarian_validate__/library")

# Per-action-variant path field names. Pulled from contract/scenario.py.
_PATH_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    "move_asset": ("to",),
    "rename_file": ("to",),
    "add_file": ("to",),
    "create_sidecar": ("to",),
    "slow_copy_start": ("to", "temp_path"),
}


def _check_root_paths(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Containment-check every ``library.roots[*].path``."""
    library = _as_mapping(raw.get("library"))
    if library is None:
        return
    roots = _as_list(library.get("roots"))
    if roots is None:
        return
    for idx, root_obj in enumerate(roots):
        root = _as_mapping(root_obj)
        if root is None:
            continue
        path = root.get("path")
        if isinstance(path, str):
            _check_containment(
                path,
                loc=("library", "roots", idx, "path"),
                line_index=line_index,
                collector=collector,
            )


def _check_timeline_paths(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Containment-check every ``to:`` / ``temp_path:`` on timeline events."""
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        action = event.get("action")
        if not isinstance(action, str):
            continue
        for field_name in _PATH_FIELDS_BY_ACTION.get(action, ()):
            value = event.get(field_name)
            if isinstance(value, str):
                _check_containment(
                    value,
                    loc=("timeline", idx, field_name),
                    line_index=line_index,
                    collector=collector,
                )


def _rule_path_containment(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject paths that violate library-root containment.

    Uses ``contract.paths.resolve_under_library`` against a synthetic
    absolute root. The helper's structural checks (absolute, ``..``,
    empty) do not require the root to exist on the filesystem. Split
    into ``_check_root_paths`` / ``_check_timeline_paths`` to stay
    under the per-function CC limit.
    """
    _check_root_paths(raw, line_index, collector)
    _check_timeline_paths(raw, line_index, collector)


def _check_containment(
    raw_path: str,
    *,
    loc: tuple[str | int, ...],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    try:
        resolve_under_library(Path(raw_path), _SYNTHETIC_LIBRARY_ROOT)
    except PathContainmentError as e:
        collector.add(
            code=codes.E_PATH_CONTAINMENT,
            severity=ValidationSeverity.ERROR,
            message=str(e),
            loc=loc,
            line_index=line_index,
        )


# ---- Registry (Tasks 7-12 add more rules here) ----------------------------


_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
    _rule_duration_syntax,
    _rule_target_unknown,
    _rule_slow_copy_unpaired,
    _rule_slow_copy_timing,
    _rule_path_containment,
]
