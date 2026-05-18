"""Tests for path containment under <run-dir>/library/."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from chaos_librarian.contract.paths import (
    PathContainmentError,
    resolve_under_library,
)


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "run" / "library"
    root.mkdir(parents=True)
    return root


def test_simple_relative_path_resolves(library_root: Path) -> None:
    resolved = resolve_under_library(Path("movies-hd/A.mkv"), library_root)
    assert resolved == (library_root / "movies-hd" / "A.mkv").resolve()


def test_nested_relative_path_resolves(library_root: Path) -> None:
    resolved = resolve_under_library(Path("a/b/c/d.mkv"), library_root)
    assert resolved == (library_root / "a" / "b" / "c" / "d.mkv").resolve()


def test_absolute_path_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="absolute"):
        resolve_under_library(Path("/etc/passwd"), library_root)


def test_absolute_path_to_library_rejected(library_root: Path) -> None:
    # Even an absolute path that happens to be inside library/ is rejected.
    # Scenario paths must be relative.
    with pytest.raises(PathContainmentError, match="absolute"):
        resolve_under_library(library_root / "A.mkv", library_root)


def test_dotdot_escape_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="escape"):
        resolve_under_library(Path("../outside.mkv"), library_root)


def test_deep_dotdot_escape_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="escape"):
        resolve_under_library(Path("movies-hd/../../outside.mkv"), library_root)


def test_dotdot_that_stays_inside_is_allowed(library_root: Path) -> None:
    resolved = resolve_under_library(Path("movies-hd/../movies-4k/A.mkv"), library_root)
    assert resolved == (library_root / "movies-4k" / "A.mkv").resolve()


def test_symlink_target_outside_library_rejected(library_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside_target"
    outside.mkdir()
    (outside / "secret.mkv").touch()

    link = library_root / "escape"
    os.symlink(outside, link)

    with pytest.raises(PathContainmentError, match="escape"):
        resolve_under_library(Path("escape/secret.mkv"), library_root)


def test_symlink_target_inside_library_allowed(library_root: Path) -> None:
    real = library_root / "movies-hd"
    real.mkdir()
    (real / "A.mkv").touch()

    link = library_root / "alias"
    os.symlink(real, link)

    resolved = resolve_under_library(Path("alias/A.mkv"), library_root)
    # Symlink resolves into the real path, which is inside library/.
    assert resolved == (real / "A.mkv").resolve()


def test_empty_path_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="empty"):
        resolve_under_library(Path(""), library_root)


def test_dot_path_rejected(library_root: Path) -> None:
    # Path(".") has parts == () on Python 3.13 (older Pythons: (".",)); the
    # parts-filter in resolve_under_library treats both as "no real
    # components" and rejects with the message that mentions "library root".
    with pytest.raises(PathContainmentError, match="library root"):
        resolve_under_library(Path("."), library_root)


def test_path_that_resolves_to_library_root_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="library root"):
        resolve_under_library(Path("movies-hd/.."), library_root)


def test_deep_path_that_resolves_to_library_root_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="library root"):
        resolve_under_library(Path("a/b/c/../../.."), library_root)
