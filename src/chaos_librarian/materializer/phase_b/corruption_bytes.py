"""Pure byte helpers for deterministic malformed-media corruption."""

from __future__ import annotations

import hashlib


def replacement_bytes(seed_material: str, byte_count: int) -> bytes:
    """Return deterministic replacement bytes derived from ``seed_material``."""
    output = bytearray()
    block_index = 0
    while len(output) < byte_count:
        block = hashlib.sha256(f"{seed_material}:{block_index}".encode()).digest()
        output.extend(block)
        block_index += 1
    return bytes(output[:byte_count])


def overwrite_range(
    data: bytes,
    *,
    byte_start: int,
    byte_count: int,
    seed_material: str,
) -> bytes:
    """Return ``data`` with exactly one deterministic byte range replaced."""
    required_length = byte_start + byte_count
    if len(data) < required_length:
        raise ValueError(
            "input file is shorter than requested corruption range: "
            f"{len(data)} < {required_length}"
        )
    output = bytearray(data)
    output[byte_start:required_length] = replacement_bytes(seed_material, byte_count)
    return bytes(output)


def truncate_bytes(data: bytes, *, keep_bytes: int) -> bytes:
    """Return the first ``keep_bytes`` bytes, rejecting non-shortening requests."""
    if keep_bytes >= len(data):
        raise ValueError(
            f"truncate_file must keep bytes shorter than input size: {keep_bytes} >= {len(data)}"
        )
    return data[:keep_bytes]
