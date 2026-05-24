"""Shared phase-B content helper tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from chaos_librarian.materializer.phase_b.content import (
    hash_bytes,
    hash_file,
    temp_sibling,
)


def test_hash_bytes_returns_sha256_uri() -> None:
    assert hash_bytes(b"abc") == "sha256:" + hashlib.sha256(b"abc").hexdigest()


def test_hash_file_returns_sha256_uri(tmp_path: Path) -> None:
    path = tmp_path / "asset.mkv"
    path.write_bytes(b"abc")

    assert hash_file(path) == "sha256:" + hashlib.sha256(b"abc").hexdigest()


def test_temp_sibling_keeps_media_suffix_at_the_end(tmp_path: Path) -> None:
    output = tmp_path / "asset.mkv"

    assert temp_sibling(output, 42) == tmp_path / "asset.tmp.42.mkv"
