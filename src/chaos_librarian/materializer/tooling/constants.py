"""Shared constants for tool wrappers and media probing."""

from __future__ import annotations

from typing import Final

# Number of trailing stderr bytes retained from a tool subprocess for error
# forensics. Bounded so a chatty tool cannot bloat journals/error payloads.
STDERR_TAIL_BYTES: Final = 2048
