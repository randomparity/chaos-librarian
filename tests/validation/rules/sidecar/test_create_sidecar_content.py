"""Per-rule tests for ``rule_create_sidecar_content`` (E_MATERIALIZE_UNSUPPORTED)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.scenario_io import LineIndex
from chaos_librarian.validation.semantic import run_semantic_pass


def _materialize_codes(raw: dict[str, object], line_index: LineIndex) -> list[str]:
    collector = IssueCollector()
    run_semantic_pass(raw, line_index, collector)
    return [i.code for i in collector.issues if i.code == codes.E_MATERIALIZE_UNSUPPORTED]


def _create_sidecar(extra: dict[str, object]) -> dict[str, object]:
    return {
        "id": "ev",
        "at": "1s",
        "action": "create_sidecar",
        "target": "a",
        "to": "r/a.eng.srt",
        "language": "eng",
        **extra,
    }


def test_srt_default_accepted(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_create_sidecar({})])
    assert _materialize_codes(raw, empty_index) == []


def test_srt_utf16_accepted(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_create_sidecar({"encoding": "utf16_le"})])
    assert _materialize_codes(raw, empty_index) == []


def test_ass_unsupported_encoding_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_create_sidecar({"codec": "ass", "encoding": "utf16_le"})])
    assert _materialize_codes(raw, empty_index) == [codes.E_MATERIALIZE_UNSUPPORTED]


def test_ass_styled_ass_utf8_accepted(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        timeline=[
            _create_sidecar(
                {
                    "to": "r/a.eng.ass",
                    "codec": "ass",
                    "source": "styled_ass",
                    "encoding": "utf8",
                }
            )
        ]
    )
    assert _materialize_codes(raw, empty_index) == []


def test_non_subtitle_kind_ignored(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "create_sidecar",
                "target": "a",
                "to": "r/a.nfo",
                "kind": "nfo",
                "body": "<movie/>",
            }
        ]
    )
    assert _materialize_codes(raw, empty_index) == []


def _poster(to: str, image_format: str | None) -> dict[str, object]:
    event: dict[str, object] = {
        "id": "ev",
        "at": "1s",
        "action": "create_sidecar",
        "target": "a",
        "to": to,
        "kind": "poster",
    }
    if image_format is not None:
        event["image_format"] = image_format
    return event


def test_poster_image_format_matching_extension_accepted(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_poster("r/cover.webp", "webp")])
    assert _materialize_codes(raw, empty_index) == []


def test_poster_image_format_jpeg_accepts_jpg_and_jpeg(minimal_scenario, empty_index) -> None:
    jpg = minimal_scenario(timeline=[_poster("r/c.jpg", "jpeg")])
    jpeg = minimal_scenario(timeline=[_poster("r/c.jpeg", "jpeg")])
    assert _materialize_codes(jpg, empty_index) == []
    assert _materialize_codes(jpeg, empty_index) == []


def test_poster_image_format_extension_mismatch_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_poster("r/cover.png", "webp")])
    assert _materialize_codes(raw, empty_index) == [codes.E_MATERIALIZE_UNSUPPORTED]


def test_poster_without_image_format_not_checked(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_poster("r/cover.png", None)])
    assert _materialize_codes(raw, empty_index) == []
