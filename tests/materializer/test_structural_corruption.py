"""Structural offsets come from declared boundaries, never payload magic."""

from pathlib import Path

import pytest

from chaos_librarian.materializer.phase_b.corruption import structure


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def element(kind: str, payload: bytes = b"") -> bytes:
    return bytes.fromhex(kind) + bytes([0x80 | len(payload)]) + payload


def mkv(children: bytes, *, unknown: bool = False) -> bytes:
    return element("1a45dfa3") + (
        bytes.fromhex("18538067ff") + children if unknown else element("18538067", children)
    )


def test_mp4_locates_box_type_after_payload_decoy() -> None:
    prefix = box(b"ftyp") + box(b"mdat", b"moov" * 8)
    data = prefix + box(b"moov", b"index")
    assert structure.resolve_header_region(data, "mp4_moov") == (len(prefix) + 4, 4)


@pytest.mark.parametrize("unknown", [False, True])
def test_mkv_ignores_cues_id_in_seekhead_payload(unknown: bool) -> None:
    children = element("114d9b74", bytes.fromhex("1c53bb6b")) + element("1c53bb6b")
    data = mkv(children, unknown=unknown)
    assert structure.resolve_header_region(data, "mkv_cues") == (len(data) - 5, 4)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"abc",
        box(b"ftyp") + b"\0" * 4,
        box(b"ftyp") + b"\xff" * 4 + b"moov",
        box(b"ftyp") + box(b"moov") * 2,
        box(b"ftyp") + b"\0\0\0\1moov",
        box(b"moov"),
        box(b"ftyp"),
    ],
)
def test_mp4_rejects_invalid_missing_duplicate_or_truncated_boxes(data: bytes) -> None:
    with pytest.raises(ValueError, match="MP4"):
        structure.resolve_header_region(data, "mp4_moov")


def test_mp4_extended_and_eof_lengths() -> None:
    prefix = box(b"ftyp")
    extended = b"\0\0\0\1moov" + (16).to_bytes(8, "big")
    assert structure.resolve_header_region(prefix + extended, "mp4_moov") == (12, 4)
    assert structure.resolve_header_region(prefix + b"\0\0\0\0moov", "mp4_moov") == (12, 4)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\0",
        mkv(b"\0"),
        mkv(b"\xec\xff"),
        mkv(element("1c53bb6b") * 2),
        mkv(element("ec")),
        mkv(b"\xec\xfe"),
        element("1a45dfa3") + b"\x18\x53",
        mkv(b"\x1c\x53\xbb\x6b\x01"),
    ],
)
def test_mkv_rejects_malformed_lengths_unknown_children_and_missing_cues(data: bytes) -> None:
    with pytest.raises(ValueError, match=r"MKV|EBML"):
        structure.resolve_header_region(data, "mkv_cues")


def test_parser_visit_budget(monkeypatch) -> None:
    monkeypatch.setattr(structure, "MAX_STRUCTURAL_ELEMENTS", 3)
    with pytest.raises(ValueError, match="limit"):
        structure.resolve_header_region(box(b"ftyp") + box(b"free") * 4 + box(b"moov"), "mp4_moov")
    with pytest.raises(ValueError, match="limit"):
        structure.resolve_header_region(mkv(element("ec") * 4 + element("1c53bb6b")), "mkv_cues")


def test_bounded_read_rejects_oversize_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(structure, "MAX_STRUCTURAL_BYTES", 16)
    path = tmp_path / "large"
    path.write_bytes(b"x" * 17)
    with pytest.raises(ValueError, match="64 MiB"):
        structure.read_structural_bytes(path)


def test_mp3_frame_prefix_is_exact_and_shortening() -> None:
    frame = b"\xff\xfb\x90\0" + bytes(413)
    data = b"ID3" + frame * 17
    assert structure.mp3_prefix_end(data, 3, 417 * 16) == 3 + 417 * 16
    for start, count in [(0, 417 * 16), (3, 417 * 16 - 1), (3, 417 * 17), (-1, 417 * 16)]:
        with pytest.raises(ValueError, match="MP3"):
            structure.mp3_prefix_end(data, start, count)


def test_mp3_rejects_reserved_header_fields() -> None:
    frame = b"\xff\xfb\x90\x02" + bytes(413)
    with pytest.raises(ValueError, match="reserved"):
        structure.mp3_prefix_end(frame * 17, 0, 417 * 16)
