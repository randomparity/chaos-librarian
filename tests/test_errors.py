"""Regression tests for the chaos-librarian exception hierarchy.

Locks in the contract that ``DurationParseError`` and ``PathContainmentError``
satisfy ``except ValueError`` (stdlib idiom + Pydantic v2 validator semantics)
AND ``except ChaosLibrarianError`` (whole-family catch).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.clock import DurationParseError, parse_duration
from chaos_librarian.contract.paths import PathContainmentError, resolve_under_library
from chaos_librarian.errors import ChaosLibrarianError, ChaosLibrarianValueError


@pytest.mark.parametrize(
    "cls",
    [DurationParseError, PathContainmentError],
    ids=["DurationParseError", "PathContainmentError"],
)
def test_value_error_subclass_satisfies_both_contracts(cls: type) -> None:
    """Both subclasses must satisfy `except ValueError` AND `except ChaosLibrarianError`."""
    assert issubclass(cls, ValueError)
    assert issubclass(cls, ChaosLibrarianError)
    assert issubclass(cls, ChaosLibrarianValueError)


def test_duration_parse_error_caught_as_value_error() -> None:
    """Instance-level catch via `except ValueError` must still work."""
    with pytest.raises(ValueError, match=r"invalid duration"):
        parse_duration("1x")


def test_path_containment_error_caught_as_value_error(tmp_path: Path) -> None:
    """Instance-level catch via `except ValueError` must still work."""
    with pytest.raises(ValueError, match=r"scenario path resolves outside library"):
        resolve_under_library(Path("../escape"), tmp_path)
