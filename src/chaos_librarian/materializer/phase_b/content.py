"""Shared phase-B content helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

_SHA256_PREFIX: Final = "sha256:"


def hash_bytes(data: bytes) -> str:
    """Return ``sha256:<hex>`` for ``data``."""
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    """Return ``sha256:<hex>`` for the file at ``path`` without full-file allocation."""
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return _SHA256_PREFIX + digest


def temp_sibling(output_path: Path, resolved_seed: int) -> Path:
    """Return a same-directory temp path that preserves the final suffix."""
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.tmp.{resolved_seed}{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.tmp.{resolved_seed}")
