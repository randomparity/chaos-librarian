"""Structural selectors preserve raw mutations and reject ambiguous intent."""

import pytest
from pydantic import ValidationError

from chaos_librarian.contract.scenario import CorruptContainerHeaderEvent, TruncateFileEvent


@pytest.mark.parametrize("region", ["mp4_moov", "mkv_cues"])
def test_structural_header_round_trip(region: str) -> None:
    event = CorruptContainerHeaderEvent.model_validate(
        {"id": "e", "at": "1s", "target": "a", "region": region}
    )
    assert event.bytes is None
    assert CorruptContainerHeaderEvent.model_validate(event.model_dump()) == event


def test_raw_header_default_remains_64_bytes() -> None:
    assert CorruptContainerHeaderEvent(id="e", at="1s", target="a").bytes == 64


@pytest.mark.parametrize("extra", [{"region": "mp4_moov", "bytes": 64}, {"region": "unknown"}])
def test_header_rejects_ambiguous_or_unknown_selector(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CorruptContainerHeaderEvent.model_validate({"id": "e", "at": "1s", "target": "a", **extra})


def test_structural_truncation_round_trip() -> None:
    event = TruncateFileEvent.model_validate(
        {"id": "e", "at": "1s", "target": "a", "boundary": "mp3_after_16_frames"}
    )
    assert event.keep_bytes is None
    assert TruncateFileEvent.model_validate(event.model_dump()) == event


@pytest.mark.parametrize(
    "extra", [{}, {"keep_bytes": 3, "boundary": "mp3_after_16_frames"}, {"boundary": "unknown"}]
)
def test_truncate_requires_one_selector(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TruncateFileEvent.model_validate({"id": "e", "at": "1s", "target": "a", **extra})


@pytest.mark.parametrize(
    ("model", "selectors"),
    [
        (CorruptContainerHeaderEvent, ("bytes", "region")),
        (TruncateFileEvent, ("keep_bytes", "boundary")),
    ],
)
def test_exported_schema_exposes_exactly_one_non_null_selector(model, selectors) -> None:
    raw, structural = selectors
    schema = model.model_json_schema()
    alternatives = schema["oneOf"]
    assert len(alternatives) == 2
    assert alternatives[0]["properties"] == {raw: {"type": "integer"}, structural: {"type": "null"}}
    assert alternatives[1]["properties"] == {raw: {"type": "null"}, structural: {"type": "string"}}
    assert alternatives[1]["required"] == [structural]
    if model is TruncateFileEvent:
        assert alternatives[0]["required"] == [raw]
    else:
        assert "required" not in alternatives[0]
