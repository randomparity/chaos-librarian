"""Root exception type for the chaos-librarian library.

Every exception the library raises inherits from ``ChaosLibrarianError`` so
callers can catch a single base class instead of enumerating concrete
subclasses (``ScenarioLoadError``, ``DurationParseError``,
``PathContainmentError``, ...).
"""

from __future__ import annotations


class ChaosLibrarianError(Exception):
    """Base class for every exception this library raises."""


__all__ = ["ChaosLibrarianError"]
