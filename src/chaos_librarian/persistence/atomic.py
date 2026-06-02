"""Canonical model serialization and per-file atomic replacement helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

__all__ = [
    "canonical_json",
    "replace_atomic_bytes",
    "replace_atomic_text",
]


def canonical_json(model: BaseModel) -> str:
    """Canonical text form of a Pydantic model: indent=2, by_alias, trailing newline."""
    payload = _dump_preserving_required_nulls(model)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def replace_atomic_text(target: Path, content: str) -> None:
    """Write ``content`` to a sibling tempfile and rename onto ``target``."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(target)


def replace_atomic_bytes(target: Path, content: bytes) -> None:
    """Write ``content`` bytes to a sibling tempfile and rename onto ``target``."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(target)


def _dump_preserving_required_nulls(model: BaseModel) -> dict[str, object]:
    raw = model.model_dump(mode="json", by_alias=True, exclude_none=False)
    if not isinstance(raw, dict):
        raise TypeError(f"expected object dump for {type(model).__name__}")
    return dict(_iter_serialized_fields(model, raw))


def _iter_serialized_fields(
    model: BaseModel,
    raw: dict[str, object],
) -> Iterable[tuple[str, object]]:
    fields = type(model).model_fields.items()
    for (field_name, field), (key, raw_value) in zip(fields, raw.items(), strict=True):
        value = getattr(model, field_name)
        if value is None:
            if field.is_required():
                yield key, None
            continue
        yield key, _dump_value_preserving_required_nulls(value, raw_value)


def _dump_value_preserving_required_nulls(value: object, raw_value: object) -> object:
    if isinstance(value, BaseModel):
        return _dump_preserving_required_nulls(value)
    if isinstance(value, list | tuple):
        if not isinstance(raw_value, list):
            return raw_value
        return [
            _dump_value_preserving_required_nulls(item, raw_item)
            for item, raw_item in zip(value, raw_value, strict=True)
        ]
    return raw_value
