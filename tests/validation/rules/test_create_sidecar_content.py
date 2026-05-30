"""Per-rule tests for ``rule_create_sidecar_content`` (E_MATERIALIZE_UNSUPPORTED).

The timeline ``create_sidecar`` subtitle path is SRT-only in v1; an ass/ssa codec
or an out-of-set encoding is rejected with the same code the declared-subtitle
path raises.
"""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
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


def test_ass_codec_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_create_sidecar({"codec": "ass", "encoding": "utf16_le"})])
    assert _materialize_codes(raw, empty_index) == [codes.E_MATERIALIZE_UNSUPPORTED]


def test_ass_codec_with_utf8_still_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_create_sidecar({"codec": "ass"})])
    assert _materialize_codes(raw, empty_index) == [codes.E_MATERIALIZE_UNSUPPORTED]


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
