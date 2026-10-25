"""Shared constants for tool wrappers and media probing."""

from __future__ import annotations

from typing import Final

# Number of trailing stderr bytes retained from a tool subprocess for error
# forensics. Bounded so a chatty tool cannot bloat journals/error payloads.
STDERR_TAIL_BYTES: Final = 2048

MAX_STRUCTURAL_BYTES: Final = 64 * 1024 * 1024
STRUCTURAL_TOOL_OUTPUT_BYTES: Final = 1024 * 1024
