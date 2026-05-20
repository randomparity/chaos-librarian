"""Path-containment helper for scenario filesystem safety.

Enforces the rules in docs/specs/chaos-librarian-design.md section
"Filesystem Safety": every scenario path is resolved under
<run-dir>/library/ and MUST stay inside it.

This module is pure (the only side effect is reading the filesystem to
resolve symlinks). It is wired into the materializer in later sprints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from chaos_librarian.errors import ChaosLibrarianValueError


class PathContainmentError(ChaosLibrarianValueError):
    """Raised when a scenario path violates the library containment contract."""


INITIAL_PATH_TEMPLATE: Final[str] = "{root_path}/{asset_id}.{container}"
"""Initial on-disk path convention for every declared asset.

Sprint 0 baked this into ``build_initial_state``'s f-string at the assignment
site; Sprint 6 lifts it to a module-level constant so the slow-copy
path-collision validation rule (``rules/slow_copy.py``) can format it
without re-encoding the convention. Format keys: ``root_path``, ``asset_id``,
``container``.

Lives in ``contract/paths.py`` (not ``engine/state.py``) to preserve the
validation→contract→errors-only layering — no validation rule imports
from ``chaos_librarian.engine``.
"""


_UNSAFE_COMPONENT_CHARS = frozenset({"/", "\\", "\x00"})
_RESERVED_COMPONENTS = frozenset({"", ".", ".."})
_FIRST_PRINTABLE_ASCII = 0x20


def is_safe_path_component(value: str) -> bool:
    """True iff ``value`` is safe to splice into a path as a single component.

    Rejects empty, ``"."``, ``".."``, any value containing a separator
    (``/`` or ``\\``), NUL bytes, or other ASCII control characters
    (``\\x00``-``\\x1f``). Mirrors the escape patterns blocked by
    ``resolve_under_library`` so that paths synthesized from components
    stay inside the library root without needing to round-trip through
    the full resolver.
    """
    if value in _RESERVED_COMPONENTS:
        return False
    if any(ch in _UNSAFE_COMPONENT_CHARS for ch in value):
        return False
    return not any(ord(ch) < _FIRST_PRINTABLE_ASCII for ch in value)


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
