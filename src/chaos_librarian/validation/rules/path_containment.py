"""Rule 6: E_PATH_CONTAINMENT — reject paths that escape library containment."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import (
    INITIAL_PATH_TEMPLATE,
    PathContainmentError,
    resolve_under_library,
)
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
    _Loc,
    _RawMapping,
    iter_assets_with_loc,
    iter_declared_roots,
    primary_root_path,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_path_containment"]


_SYNTHETIC_LIBRARY_ROOT: Path = Path("/__chaos_librarian_validate__/library")

# Per-action-variant path field names. Keys are the discriminator values
# declared on TimelineEvent variants in contract/scenario.py; using the
# StrEnum binds this map to the contract symbol set at the type level —
# adding/renaming an action surfaces here, not as a silent miss.
_PATH_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    TimelineActionName.MOVE_ASSET: ("to",),
    TimelineActionName.RENAME_FILE: ("to",),
    TimelineActionName.ADD_FILE: ("to",),
    TimelineActionName.CREATE_SIDECAR: ("to",),
    TimelineActionName.SLOW_COPY_START: ("to", "temp_path"),
}


def rule_path_containment(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject paths that violate library-root containment.

    Uses ``contract.paths.resolve_under_library`` against a synthetic
    absolute root. The helper's structural checks (absolute, ``..``,
    empty) do not require the root to exist on the filesystem.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    _check_root_paths(raw, reporter)
    _check_timeline_paths(raw, reporter)
    _check_synthesized_timeline_paths(raw, reporter)


def _check_root_paths(raw: Mapping[str, object], reporter: Reporter) -> None:
    """Containment-check every ``library.roots[*].path``."""
    roots = _list_at_path(raw, ("library", "roots"))
    if roots is None:
        return
    for idx, root_obj in enumerate(roots):
        root = _as_mapping(root_obj)
        if root is None:
            continue
        path = root.get("path")
        if isinstance(path, str):
            _check_containment(path, loc=("library", "roots", idx, "path"), reporter=reporter)


def _check_timeline_paths(raw: Mapping[str, object], reporter: Reporter) -> None:
    """Containment-check every ``to:`` / ``temp_path:`` on timeline events."""
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not isinstance(action, str):
            continue
        for field_name in _PATH_FIELDS_BY_ACTION.get(action, ()):
            value = event.get(field_name)
            if isinstance(value, str):
                _check_containment(value, loc=("timeline", idx, field_name), reporter=reporter)


def _check_synthesized_timeline_paths(raw: _RawMapping, reporter: Reporter) -> None:
    """Containment-check synthesized destinations for actions with no ``to:`` field.

    ``archive_file`` and ``move_between_roots`` derive their destination
    from library config (the archive root / target root path plus the
    asset container) the same way the engine handlers do via
    ``state.archive_path_for`` and ``state.root_path_for``. The rule
    must run the synthesized path through containment so an escape via
    library config is caught at validate-time, not at materialize-time.
    """
    declared_roots = {
        root_id: path for root_id, path in iter_declared_roots(raw) if path is not None
    }
    archive_base = _archive_base_path(raw, declared_roots)
    asset_containers = _asset_containers(raw)

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action == TimelineActionName.ARCHIVE_FILE:
            _check_archive_file(
                event,
                idx=idx,
                archive_base=archive_base,
                asset_containers=asset_containers,
                reporter=reporter,
            )
        elif action == TimelineActionName.MOVE_BETWEEN_ROOTS:
            _check_move_between_roots(
                event,
                idx=idx,
                declared_roots=declared_roots,
                asset_containers=asset_containers,
                reporter=reporter,
            )


def _check_archive_file(
    event: _RawMapping,
    *,
    idx: int,
    archive_base: str | None,
    asset_containers: Mapping[str, str],
    reporter: Reporter,
) -> None:
    """Synthesize and check the archive destination for one ``archive_file``."""
    target = event.get("target")
    if not isinstance(target, str) or archive_base is None:
        return
    container = asset_containers.get(target)
    if container is None:
        return
    synthesized = INITIAL_PATH_TEMPLATE.format(
        root_path=archive_base, asset_id=target, container=container
    )
    _check_containment(synthesized, loc=("timeline", idx, "target"), reporter=reporter)


def _check_move_between_roots(
    event: _RawMapping,
    *,
    idx: int,
    declared_roots: Mapping[str, str],
    asset_containers: Mapping[str, str],
    reporter: Reporter,
) -> None:
    """Synthesize and check the destination for one ``move_between_roots``."""
    target = event.get("target")
    to_root_id = event.get("to_root_id")
    if not isinstance(target, str) or not isinstance(to_root_id, str):
        return
    to_root_path = declared_roots.get(to_root_id)
    container = asset_containers.get(target)
    if to_root_path is None or container is None:
        return
    synthesized = INITIAL_PATH_TEMPLATE.format(
        root_path=to_root_path, asset_id=target, container=container
    )
    _check_containment(synthesized, loc=("timeline", idx, "to_root_id"), reporter=reporter)


def _archive_base_path(
    raw: _RawMapping,
    declared_roots: Mapping[str, str],
) -> str | None:
    """Return the archive base path, mirroring ``build_initial_state``.

    Sentinel ``"archive"`` and ``None`` both resolve to
    ``<primary_root.path>/archive``. A named ``archive_root`` resolves to
    that declared root's path. Returns ``None`` when the library subtree
    is malformed enough to defeat the lookup — the shape pass (or
    ``rule_root_unknown``) owns those error reports.
    """
    primary_path = primary_root_path(raw)
    if primary_path is None:
        return None
    library = _as_mapping(raw.get("library"))
    archive_root = library.get("archive_root") if library is not None else None
    if archive_root is None or archive_root == "archive":
        return f"{primary_path}/archive"
    if isinstance(archive_root, str):
        return declared_roots.get(archive_root)
    return None


def _asset_containers(raw: _RawMapping) -> dict[str, str]:
    """Return ``{asset_id: container}`` for every well-shaped declared asset."""
    containers: dict[str, str] = {}
    for asset, _ in iter_assets_with_loc(raw):
        asset_id = asset.get("id")
        container = asset.get("container")
        if isinstance(asset_id, str) and isinstance(container, str):
            containers[asset_id] = container
    return containers


def _check_containment(raw_path: str, *, loc: _Loc, reporter: Reporter) -> None:
    try:
        resolve_under_library(Path(raw_path), _SYNTHETIC_LIBRARY_ROOT)
    except PathContainmentError as e:
        reporter.error(code=E_PATH_CONTAINMENT, message=str(e), loc=loc)
