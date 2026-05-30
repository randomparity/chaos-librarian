"""corrupt_tags timeline event + TagCorruptionFlavor (#118)."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import (
    CorruptTagsEvent,
    TagCorruptionFlavor,
    TimelineActionName,
)


def test_corrupt_tags_defaults() -> None:
    event = CorruptTagsEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "a", "flavor": "null_bytes"}
    )
    assert event.action is TimelineActionName.CORRUPT_TAGS
    assert event.flavor is TagCorruptionFlavor.NULL_BYTES
    assert event.bytes == 64


def test_corrupt_tags_malformed_frame() -> None:
    event = CorruptTagsEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "a", "flavor": "malformed_frame", "bytes": 10}
    )
    assert event.flavor is TagCorruptionFlavor.MALFORMED_FRAME
    assert event.bytes == 10


def test_corrupt_tags_bytes_lower_bound() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        CorruptTagsEvent.model_validate(
            {"id": "e1", "at": "0s", "target": "a", "flavor": "malformed_frame", "bytes": 0}
        )


def test_corrupt_tags_rejects_unknown_flavor() -> None:
    with pytest.raises(ValueError, match="flavor"):
        CorruptTagsEvent.model_validate(
            {"id": "e1", "at": "0s", "target": "a", "flavor": "scramble"}
        )
