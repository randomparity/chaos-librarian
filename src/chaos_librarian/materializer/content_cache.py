"""Content-addressed cache primitives for future file-backed content sources."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_CACHE_ENV: Final = "CHAOS_LIBRARIAN_CONTENT_CACHE"
_SHA256_PREFIX: Final = "sha256:"
_SHA256_HEX_LENGTH: Final = 64
_LOWER_HEX_DIGITS: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class CacheProbe:
    root: Path
    writable: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class CacheRecord:
    cache_key: str
    content_hash: str
    path: Path


def cache_key_for_bytes(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"{_SHA256_PREFIX}{digest}"


def cache_key_for_path(path: Path) -> str:
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return f"{_SHA256_PREFIX}{digest}"


def default_content_cache_root() -> Path:
    env_root = os.environ.get(_CACHE_ENV)
    if env_root:
        return Path(env_root).expanduser()

    if sys.platform == "darwin":
        return Path("~/Library/Caches/chaos-librarian/content-sources").expanduser()

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "chaos-librarian" / "Cache" / "content-sources"
        return Path("~/AppData/Local/chaos-librarian/Cache/content-sources").expanduser()

    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "chaos-librarian" / "content-sources"
    return Path("~/.cache/chaos-librarian/content-sources").expanduser()


def probe_content_cache(root: Path | None = None) -> CacheProbe:
    cache_root = default_content_cache_root() if root is None else root
    probe_target = cache_root if cache_root.exists() else cache_root.parent

    if not probe_target.exists():
        return CacheProbe(root=cache_root, writable=False, reason="parent_missing")
    if not os.access(probe_target, os.W_OK):
        return CacheProbe(root=cache_root, writable=False, reason="not_writable")
    return CacheProbe(root=cache_root, writable=True, reason=None)


class ContentCache:
    def __init__(self, root: Path | None = None) -> None:
        self.root = default_content_cache_root() if root is None else root

    def path_for(self, *, cache_key: str) -> Path:
        digest = _digest_from_cache_key(cache_key)
        return self.root / digest[:2] / digest[2:4] / digest

    def lookup(self, *, cache_key: str) -> CacheRecord | None:
        path = self.path_for(cache_key=cache_key)
        if not path.exists():
            return None

        content_hash = cache_key_for_path(path)
        if content_hash != cache_key:
            raise ValueError(f"cached content hash mismatch for {cache_key}: found {content_hash}")
        return CacheRecord(cache_key=cache_key, content_hash=content_hash, path=path)

    def store_bytes(self, *, cache_key: str, content: bytes) -> CacheRecord:
        content_hash = cache_key_for_bytes(content)
        if content_hash != cache_key:
            raise ValueError(f"content hash mismatch for {cache_key}: computed {content_hash}")

        path = self.path_for(cache_key=cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _sibling_temp_path(path)
        try:
            temp_path.write_bytes(content)
            temp_path.replace(path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return CacheRecord(cache_key=cache_key, content_hash=content_hash, path=path)

    def store_file(self, *, cache_key: str, source_path: Path) -> CacheRecord:
        content_hash = cache_key_for_path(source_path)
        if content_hash != cache_key:
            raise ValueError(f"content hash mismatch for {cache_key}: computed {content_hash}")

        path = self.path_for(cache_key=cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _sibling_temp_path(path)
        try:
            with source_path.open("rb") as source, temp_path.open("wb") as target:
                shutil.copyfileobj(source, target)
            temp_path.replace(path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return CacheRecord(cache_key=cache_key, content_hash=content_hash, path=path)


def _digest_from_cache_key(cache_key: str) -> str:
    if not cache_key.startswith(_SHA256_PREFIX):
        raise ValueError(f"cache key must be a sha256 URI: {cache_key}")

    digest = cache_key.removeprefix(_SHA256_PREFIX)
    if len(digest) != _SHA256_HEX_LENGTH:
        raise ValueError(f"cache key must contain 64 lowercase sha256 hex chars: {cache_key}")
    if any(char not in _LOWER_HEX_DIGITS for char in digest):
        raise ValueError(f"cache key must contain 64 lowercase sha256 hex chars: {cache_key}")
    return digest


def _sibling_temp_path(path: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temp:
        temp_path = Path(temp.name)
    return temp_path
