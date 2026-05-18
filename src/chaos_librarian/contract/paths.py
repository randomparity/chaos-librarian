"""Path-containment helper for scenario filesystem safety.

Enforces the rules in docs/specs/chaos-librarian-design.md section
"Filesystem Safety": every scenario path is resolved under
<run-dir>/library/ and MUST stay inside it.

This module is pure (the only side effect is reading the filesystem to
resolve symlinks). It is wired into the materializer in later sprints.
"""

from __future__ import annotations

from pathlib import Path


class PathContainmentError(ValueError):
    """Raised when a scenario path violates the library containment contract."""


def resolve_under_library(candidate: Path, library_root: Path) -> Path:
    """Resolve a scenario path under the library root, rejecting any escape.

    Scenario paths MUST resolve to a strict subpath of ``library_root``; a
    path that resolves exactly to the library root is rejected because
    later cleanup and materializer code receives it as an asset target.

    Args:
        candidate: Path from a scenario field. MUST be relative.
        library_root: Absolute path to ``<run-dir>/library/``.

    Returns:
        The resolved absolute path, guaranteed to be a strict subpath of
        ``library_root``.

    Raises:
        PathContainmentError: If ``candidate`` is absolute, empty, resolves
            to the library root itself, contains ``..`` segments that escape
            ``library_root``, or follows a symlink whose target is outside
            ``library_root``.
    """
    # Reject empty paths, bare-dot paths, and paths whose only segments are
    # "." or empty up front. On Python 3.13, Path("") and Path(".") both have
    # parts == (); on earlier Pythons they have ("",) or (".",). Filtering
    # those segments handles every version and also rejects Path("./.").
    parts = tuple(p for p in candidate.parts if p not in ("", "."))
    if not parts:
        raise PathContainmentError(
            f"scenario path is empty or resolves to library root (no real components): "
            f"{candidate!r}"
        )

    if candidate.is_absolute():
        raise PathContainmentError(f"scenario path must be relative, got absolute: {candidate}")

    library_root_resolved = library_root.resolve(strict=False)
    joined = library_root_resolved / candidate
    resolved = joined.resolve(strict=False)

    # Strict subpath: must NOT equal the library root itself.
    if resolved == library_root_resolved:
        raise PathContainmentError(
            f"scenario path resolves to library root (must be strict subpath): "
            f"{candidate} -> {resolved}"
        )
    if library_root_resolved not in resolved.parents:
        raise PathContainmentError(
            f"scenario path resolves outside library (escape): "
            f"{candidate} -> {resolved} (library: {library_root_resolved})"
        )
    return resolved
