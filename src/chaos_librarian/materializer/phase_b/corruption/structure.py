"""Bounded locators for the three generated-media structural corruption recipes."""

from pathlib import Path
from typing import Final

MAX_STRUCTURAL_BYTES: Final = 64 * 1024 * 1024
MAX_STRUCTURAL_ELEMENTS: Final = 4096
STRUCTURAL_TOOL_OUTPUT_BYTES: Final = 1024 * 1024
_MP4_HEADER_BYTES: Final = 8
_MP4_EXTENDED_HEADER_BYTES: Final = 16
_EBML_HEADER_ID: Final = 0x1A45DFA3
_SEGMENT_ID: Final = 0x18538067
_CUES_ID: Final = 0x1C53BB6B
_MP3_HEADER_BYTES: Final = 4
_MP3_SYNC: Final = 0x7FF
_MP3_RESERVED_EMPHASIS: Final = 2
_MPEG1_LAYER3: Final = 0b1101
_MP3_BITRATES: Final = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)


def read_structural_bytes(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_STRUCTURAL_BYTES + 1)
    if len(data) > MAX_STRUCTURAL_BYTES:
        raise ValueError("structural corruption input exceeds 64 MiB")
    return data


def resolve_header_region(data: bytes, region: str) -> tuple[int, int]:
    if len(data) > MAX_STRUCTURAL_BYTES:
        raise ValueError("structural corruption input exceeds 64 MiB")
    if region == "mp4_moov":
        return _mp4_moov(data), 4
    if region == "mkv_cues":
        return _mkv_cues(data), 4
    raise ValueError(f"unsupported structural region: {region!r}")


def _mp4_box(data: bytes, offset: int) -> tuple[bytes, int]:
    remaining = len(data) - offset
    if remaining < _MP4_HEADER_BYTES:
        raise ValueError("truncated MP4 box header")
    size = int.from_bytes(data[offset : offset + 4], "big")
    kind = data[offset + 4 : offset + 8]
    header = 8
    if size == 1:
        if remaining < _MP4_EXTENDED_HEADER_BYTES:
            raise ValueError("truncated extended MP4 box header")
        size = int.from_bytes(data[offset + 8 : offset + 16], "big")
        header = 16
    elif size == 0:
        size = remaining
    if not header <= size <= remaining:
        raise ValueError("invalid MP4 box length")
    return kind, offset + size


def _mp4_moov(data: bytes) -> int:
    offset = 0
    found = None
    ftyp = False
    for _ in range(MAX_STRUCTURAL_ELEMENTS):
        if offset == len(data):
            break
        kind, end = _mp4_box(data, offset)
        ftyp = ftyp or kind == b"ftyp"
        if kind == b"moov":
            if found is not None:
                raise ValueError("duplicate MP4 moov box")
            found = offset + 4
        offset = end
    if offset != len(data):
        raise ValueError("MP4 exceeds element visit limit")
    if found is None or not ftyp:
        raise ValueError("MP4 requires ftyp and one moov box")
    return found


def _vint(data: bytes, offset: int, end: int, *, identifier: bool) -> tuple[int, int, bool]:
    if offset >= end or data[offset] == 0:
        raise ValueError("missing or invalid EBML integer")
    width = 9 - data[offset].bit_length()
    if width > (4 if identifier else 8) or width > end - offset:
        raise ValueError("invalid or truncated EBML integer width")
    value = int.from_bytes(data[offset : offset + width], "big")
    if identifier:
        return value, offset + width, False
    value &= (1 << (7 * width)) - 1
    return value, offset + width, value == (1 << (7 * width)) - 1


def _element(data: bytes, offset: int, end: int) -> tuple[int, int, int, bool]:
    kind, after_id, _ = _vint(data, offset, end, identifier=True)
    size, payload, unknown = _vint(data, after_id, end, identifier=False)
    if not unknown and size > end - payload:
        raise ValueError("EBML element length exceeds parent")
    return kind, payload, end if unknown else payload + size, unknown


def _mkv_cues(data: bytes) -> int:
    kind, _, header_end, unknown = _element(data, 0, len(data))
    if kind != _EBML_HEADER_ID or unknown:
        raise ValueError("MKV requires a sized EBML header")
    kind, offset, end, _ = _element(data, header_end, len(data))
    if kind != _SEGMENT_ID or end != len(data):
        raise ValueError("MKV requires one complete Segment after the EBML header")
    found = None
    for _ in range(MAX_STRUCTURAL_ELEMENTS):
        if offset == end:
            break
        kind, _, next_offset, unknown = _element(data, offset, end)
        if unknown:
            raise ValueError("unknown-size MKV Segment children are unsupported")
        if kind == _CUES_ID:
            if found is not None:
                raise ValueError("duplicate MKV Cues")
            found = offset
        offset = next_offset
    if offset != end:
        raise ValueError("MKV exceeds element visit limit")
    if found is None:
        raise ValueError("MKV requires a Cues element")
    return found


def mp3_prefix_end(data: bytes, byte_start: int, byte_count: int) -> int:
    """Verify the packet-selected prefix ends after sixteen MPEG-1 Layer III frames."""
    end = byte_start + byte_count
    if byte_start < 0 or byte_count <= 0 or end >= len(data):
        raise ValueError("MP3 boundary must retain a positive prefix shorter than input")
    offset = byte_start
    for _ in range(16):
        if end - offset < _MP3_HEADER_BYTES:
            raise ValueError("truncated MP3 frame header")
        header = int.from_bytes(data[offset : offset + 4], "big")
        bitrate_index = (header >> 12) & 15
        if header & 3 == _MP3_RESERVED_EMPHASIS:
            raise ValueError("MP3 frame uses reserved emphasis bits")
        if header >> 21 != _MP3_SYNC or (header >> 17) & 15 != _MPEG1_LAYER3:
            raise ValueError("MP3 boundary requires MPEG-1 Layer III frames")
        if (header >> 10) & 3 != 0 or not 1 <= bitrate_index < len(_MP3_BITRATES):
            raise ValueError("MP3 boundary requires 44.1 kHz and a supported bitrate")
        offset += 144000 * _MP3_BITRATES[bitrate_index] // 44100 + ((header >> 9) & 1)
        if offset > end:
            raise ValueError("MP3 frame extends beyond packet-selected boundary")
    if offset != end:
        raise ValueError("MP3 packet range does not contain exactly sixteen complete frames")
    return end
