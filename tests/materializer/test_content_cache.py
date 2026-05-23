"""Tests for content-source cache policy primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.materializer.content_cache import (
    ContentCache,
    cache_key_for_bytes,
    cache_key_for_path,
    default_content_cache_root,
    probe_content_cache,
)


def test_cache_key_for_bytes_is_sha256_uri() -> None:
    assert (
        cache_key_for_bytes(b"abc")
        == "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_cache_key_for_path_streams_file_digest(tmp_path: Path) -> None:
    path = tmp_path / "clip.bin"
    path.write_bytes(b"abc")

    assert cache_key_for_path(path) == cache_key_for_bytes(b"abc")


def test_store_bytes_writes_content_addressed_path(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"payload")

    record = cache.store_bytes(cache_key=key, content=b"payload")

    assert record.cache_key == key
    assert record.content_hash == key
    assert record.path == cache.path_for(cache_key=key)
    assert record.path.read_bytes() == b"payload"


def test_store_file_writes_content_addressed_path(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    key = cache_key_for_path(source)

    record = cache.store_file(cache_key=key, source_path=source)

    assert record.cache_key == key
    assert record.content_hash == key
    assert record.path.read_bytes() == b"payload"


def test_lookup_returns_none_for_missing_key(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"missing")

    assert cache.lookup(cache_key=key) is None


def test_lookup_returns_existing_record(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"payload")
    cache.store_bytes(cache_key=key, content=b"payload")

    record = cache.lookup(cache_key=key)

    assert record is not None
    assert record.cache_key == key
    assert record.content_hash == key
    assert record.path.read_bytes() == b"payload"


def test_lookup_rejects_corrupt_cached_bytes(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"payload")
    path = cache.path_for(cache_key=key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered")

    with pytest.raises(ValueError, match="cached content hash mismatch"):
        cache.lookup(cache_key=key)


def test_store_bytes_rejects_digest_mismatch(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    key = cache_key_for_bytes(b"expected")

    with pytest.raises(ValueError, match="content hash mismatch"):
        cache.store_bytes(cache_key=key, content=b"actual")


def test_path_for_rejects_non_sha256_uri(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)

    with pytest.raises(ValueError, match="sha256"):
        cache.path_for(cache_key="../escape")


def test_probe_content_cache_reports_writable_existing_root(tmp_path: Path) -> None:
    probe = probe_content_cache(tmp_path)

    assert probe.root == tmp_path
    assert probe.writable is True
    assert probe.reason is None


def test_default_cache_root_honors_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    custom = tmp_path / "cache"
    monkeypatch.setenv("CHAOS_LIBRARIAN_CONTENT_CACHE", str(custom))

    assert default_content_cache_root() == custom
