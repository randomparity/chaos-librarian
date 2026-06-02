"""Pure byte helpers for deterministic malformed-media corruption."""

from __future__ import annotations

import hashlib
from typing import Final


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


def zero_range(data: bytes, *, byte_start: int, byte_count: int) -> bytes:
    """Return ``data`` with ``byte_count`` bytes from ``byte_start`` set to 0x00.

    Models embedded null bytes in a tag region (corrupt_tags ``null_bytes``).
    Same length guard as ``overwrite_range``; the file size is unchanged.
    """
    required_length = byte_start + byte_count
    if len(data) < required_length:
        raise ValueError(
            "input file is shorter than requested corruption range: "
            f"{len(data)} < {required_length}"
        )
    output = bytearray(data)
    output[byte_start:required_length] = b"\x00" * byte_count
    return bytes(output)


# A deliberately invalid ID3v2 header: the ``ID3`` magic followed by a bogus
# version (0xFF 0xFF — no such ID3v2 minor version) and non-syncsafe size/flags
# bytes (0xFF). A real ID3v2 header never has 0xFF in these positions, so this
# is a malformed tag a probe rejects or mis-parses (corrupt_tags ``malformed_frame``).
_MALFORMED_ID3_HEADER: Final = bytes((0x49, 0x44, 0x33, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF))


def malformed_id3_header(data: bytes, *, byte_count: int) -> bytes:
    """Overwrite ``byte_count`` head bytes in place with a fixed invalid ID3v2 header.

    The pattern is tiled/truncated to ``byte_count``; the file size is unchanged
    so all downstream offsets stay valid.
    """
    if len(data) < byte_count:
        raise ValueError(
            f"input file is shorter than requested header span: {len(data)} < {byte_count}"
        )
    repeats = byte_count // len(_MALFORMED_ID3_HEADER) + 1
    pattern = (_MALFORMED_ID3_HEADER * repeats)[:byte_count]
    output = bytearray(data)
    output[:byte_count] = pattern
    return bytes(output)
