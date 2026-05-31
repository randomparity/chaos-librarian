"""Escaping symlink-target containment check (E_SYMLINK_TARGET_ESCAPE).

``rule_symlink_target_escape`` classifies every ``symlink.to_run_dir_path``
(scenario v27): an escaping symlink target MUST resolve inside the run dir but
**outside** ``library/`` ("external to the library root, internal to the
sandbox"). A target inside ``library/`` (use ``to_asset`` instead), equal to the
run dir, absolute, or escaping the run dir is rejected with
``E_SYMLINK_TARGET_ESCAPE``.

This is deliberately distinct from ``E_PATH_CONTAINMENT``: escaping the *library*
is the intended chaos for the ``scanner/symlink-external`` shape, so it must not be
a containment violation, but escaping the *run-dir sandbox* must still fail. The
rule resolves against a synthetic run-dir root and never calls
``resolve_under_library``, leaving ``E_PATH_CONTAINMENT`` untouched. The in-root
``symlink.to_asset`` form is ignored here; it is resolved by
``rule_content_reference`` (``E_TARGET_UNKNOWN``).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from chaos_librarian.validation.codes import E_SYMLINK_TARGET_ESCAPE
from chaos_librarian.validation.rules.hierarchy_walkers import iter_assets_with_loc
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _as_mapping,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_symlink_target_escape"]


_SYNTHETIC_RUN_DIR: Path = Path("/__chaos_librarian_validate__")
_SYNTHETIC_LIBRARY_DIR: Path = _SYNTHETIC_RUN_DIR / "library"

_ESCAPES_SANDBOX = "symlink target escapes the run-dir sandbox"
_IN_LIBRARY = "escaping symlink target must be outside library/; use to_asset for in-root links"


def rule_symlink_target_escape(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject ``symlink.to_run_dir_path`` targets that leave the run-dir sandbox.

    Accepts iff the target resolves to a strict subpath of the run dir that is
    not equal to, nor inside, ``library/``.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    for asset, asset_loc in iter_assets_with_loc(raw):
        symlink = _as_mapping(asset.get("symlink"))
        if symlink is None:
            continue
        target = symlink.get("to_run_dir_path")
        if not isinstance(target, str):
            continue  # to_asset form (or absent) is not this rule's concern.
        loc = (*asset_loc, "symlink", "to_run_dir_path")
        message = _classify_target(target)
        if message is not None:
            reporter.error(code=E_SYMLINK_TARGET_ESCAPE, message=message, loc=loc)


def _classify_target(target: str) -> str | None:
    """Return a rejection message, or ``None`` when the target is in-sandbox.

    The run-dir-escape check runs before the library check so an absolute path
    or a ``..``-escape is reported as a sandbox escape rather than mis-reported
    as a library-boundary error.
    """
    candidate = Path(target)
    if candidate.is_absolute():
        return _ESCAPES_SANDBOX
    resolved = (_SYNTHETIC_RUN_DIR / candidate).resolve(strict=False)
    if resolved == _SYNTHETIC_RUN_DIR or _SYNTHETIC_RUN_DIR not in resolved.parents:
        return _ESCAPES_SANDBOX
    if resolved == _SYNTHETIC_LIBRARY_DIR or _SYNTHETIC_LIBRARY_DIR in resolved.parents:
        return _IN_LIBRARY
    return None
