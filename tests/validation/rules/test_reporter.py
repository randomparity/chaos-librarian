"""Unit tests for ``Reporter`` — the per-rule ``collector + line_index`` handle.

WHY: ``Reporter`` is used by every rule module; if its dataclass form
fails to construct (PEP 563 + ``slots=True`` + forward-ref annotation
interaction), every rule breaks. Pinning the smoke test as its own
fast file means a regression here surfaces before touching any rule.
"""

from __future__ import annotations

import dataclasses

import pytest

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import E_ID_DUPLICATE, E_PATH_DUPLICATE
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules._common import Reporter


def test_reporter_constructs_under_pep563_with_slots() -> None:
    """``Reporter(collector, line_index)`` must construct without resolving
    forward-ref type annotations at class build time. If this regresses
    (e.g. a future ``dataclass``/``slots`` change calls ``get_type_hints``),
    every rule breaks; catch it here."""
    reporter = Reporter(collector=IssueCollector(), line_index=LineIndex())
    assert reporter.collector.issues == []


def test_reporter_error_emits_one_error_issue() -> None:
    """``reporter.error`` records a single ERROR-severity issue with the
    bound ``line_index`` and the call's ``code``/``message``/``loc``."""
    collector = IssueCollector()
    reporter = Reporter(collector=collector, line_index=LineIndex())

    reporter.error(code=E_ID_DUPLICATE, message="dup", loc=("movies", 0, "id"))

    assert len(collector.issues) == 1
    issue = collector.issues[0]
    assert issue.severity == ValidationSeverity.ERROR
    assert issue.code == E_ID_DUPLICATE
    assert issue.message == "dup"


def test_reporter_warning_emits_one_warning_issue() -> None:
    """``reporter.warning`` is the WARNING-severity twin of ``.error``;
    only ``path_duplicate`` uses it today but the API must round-trip."""
    collector = IssueCollector()
    reporter = Reporter(collector=collector, line_index=LineIndex())

    reporter.warning(code=E_PATH_DUPLICATE, message="warn", loc=())

    assert len(collector.issues) == 1
    assert collector.issues[0].severity == ValidationSeverity.WARNING
    assert collector.issues[0].code == E_PATH_DUPLICATE


def test_reporter_is_frozen() -> None:
    """``Reporter`` is ``frozen=True`` so a helper cannot accidentally
    rebind ``collector``/``line_index`` mid-rule. Uses ``setattr`` to
    bypass static type-checking of the frozen attribute write — the
    runtime guard is what we're verifying."""
    reporter = Reporter(collector=IssueCollector(), line_index=LineIndex())

    # ``setattr`` keeps the attribute name a string so ty doesn't statically
    # reject the frozen-field rebind — the runtime ``__setattr__`` raise is
    # what this test verifies.
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(reporter, "collector", IssueCollector())  # noqa: B010
