"""Root exception type for the chaos-librarian library.

Every exception the library raises inherits from ``ChaosLibrarianError`` so
callers can catch a single base class instead of enumerating concrete
subclasses (``ScenarioLoadError``, ``DurationParseError``,
``PathContainmentError``, ...).

Value-format errors (``DurationParseError``, ``PathContainmentError``)
additionally inherit from ``ValueError`` via ``ChaosLibrarianValueError``
so they satisfy both the stdlib-idiom ``except ValueError`` contract and
Pydantic v2 field-validator semantics, which only wrap ``ValueError`` /
``AssertionError`` cleanly into ``ValidationError``.
"""

from __future__ import annotations


class ChaosLibrarianError(Exception):
    """Base class for every exception this library raises."""


class ChaosLibrarianValueError(ValueError, ChaosLibrarianError):
    """Base for value-format errors that must also satisfy ``except ValueError``."""


__all__ = ["ChaosLibrarianError", "ChaosLibrarianValueError"]
