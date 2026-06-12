"""Post-hoc run visualizer: replay a run dir into a self-contained HTML timeline."""

from __future__ import annotations

from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    MissingArtifactError,
    ScenarioRevalidationError,
)
from chaos_librarian.visualize.payload import build_payload
from chaos_librarian.visualize.render import render_html

__all__ = [
    "JournalCorruptLineError",
    "JournalDivergenceError",
    "MissingArtifactError",
    "ScenarioRevalidationError",
    "build_payload",
    "render_html",
]
