"""Stable error-code constants, Pydantic→code map, and JSONPath formatter.

Codes are part of the public contract (see
``docs/superpowers/specs/2026-05-17-sprint-1-validate-design.md``
§"Error Code Reference"). Adding new codes is allowed; renaming or
removing one is breaking.
"""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.scenario import ALL_TIMELINE_ACTIONS

# ---- Code constants --------------------------------------------------------

E_YAML_PARSE: Final = "E_YAML_PARSE"
E_TOP_LEVEL_NOT_MAPPING: Final = "E_TOP_LEVEL_NOT_MAPPING"
E_FIELD_MISSING: Final = "E_FIELD_MISSING"
E_FIELD_UNKNOWN: Final = "E_FIELD_UNKNOWN"
E_FIELD_LITERAL: Final = "E_FIELD_LITERAL"
E_FIELD_TYPE: Final = "E_FIELD_TYPE"
E_FIELD_SHAPE: Final = "E_FIELD_SHAPE"
E_TIMELINE_ACTION_UNKNOWN: Final = "E_TIMELINE_ACTION_UNKNOWN"
E_DURATION_SYNTAX: Final = "E_DURATION_SYNTAX"
E_ID_DUPLICATE: Final = "E_ID_DUPLICATE"
E_TARGET_UNKNOWN: Final = "E_TARGET_UNKNOWN"
E_ROOT_UNKNOWN: Final = "E_ROOT_UNKNOWN"
E_SLOW_COPY_UNPAIRED: Final = "E_SLOW_COPY_UNPAIRED"
E_SLOW_COPY_TIMING: Final = "E_SLOW_COPY_TIMING"
E_SLOW_COPY_PATH_COLLISION: Final = "E_SLOW_COPY_PATH_COLLISION"
E_PATH_CONTAINMENT: Final = "E_PATH_CONTAINMENT"
E_PATH_DUPLICATE: Final = "E_PATH_DUPLICATE"
E_TIMELINE_ORDER: Final = "E_TIMELINE_ORDER"
E_LIFECYCLE_INVALID: Final = "E_LIFECYCLE_INVALID"
E_SIDECAR_LANGUAGE_INVALID: Final = "E_SIDECAR_LANGUAGE_INVALID"


# ---- Pydantic error-type → chaos-librarian code ----------------------------

PYDANTIC_TO_CODE: Final[dict[str, str]] = {
    "missing": E_FIELD_MISSING,
    "extra_forbidden": E_FIELD_UNKNOWN,
    "literal_error": E_FIELD_LITERAL,
    # StrEnum-backed fields (SubtitleMode, DurationScale, StreamKind, etc.)
    # raise ``enum`` rather than ``literal_error`` even though the closed-set
    # semantic is identical — fold both into E_FIELD_LITERAL so consumers see
    # one stable code regardless of which annotation form the contract uses.
    "enum": E_FIELD_LITERAL,
    # Type-shape errors: every Pydantic primitive type-check funnels to E_FIELD_TYPE.
    "string_type": E_FIELD_TYPE,
    "int_type": E_FIELD_TYPE,
    "float_type": E_FIELD_TYPE,
    "bool_type": E_FIELD_TYPE,
    "list_type": E_FIELD_TYPE,
    # ``tuple_type`` covers the Scenario subtree's tuple-backed collection
    # fields (``library.roots``, ``works``, ``timeline``, etc.). Without this
    # entry Pydantic's ``tuple_type`` error would degrade to E_FIELD_SHAPE
    # instead of the stable E_FIELD_TYPE contract.
    "tuple_type": E_FIELD_TYPE,
    "dict_type": E_FIELD_TYPE,
    "model_type": E_FIELD_TYPE,
    # Discriminated-union failures on Scenario.timeline.
    "union_tag_invalid": E_TIMELINE_ACTION_UNKNOWN,
    "union_tag_not_found": E_TIMELINE_ACTION_UNKNOWN,
}


# ---- JSONPath formatting ---------------------------------------------------

# Discriminator values that Pydantic inserts mid-loc for Scenario.timeline.
# Source of truth: ``ALL_TIMELINE_ACTIONS`` in contract.scenario.
_DISCRIMINATOR_TAGS: Final[frozenset[str]] = ALL_TIMELINE_ACTIONS

# Pydantic emits Python field names in loc tuples. Map them back to the
# YAML/JSON alias used in the user's scenario file.
_ALIAS_REWRITES: Final[dict[str, str]] = {
    "for_": "for",
}


def format_jsonpath(loc: tuple[str | int, ...]) -> str:
    """Convert a Pydantic-style loc tuple to a JSONPath string.

    Scenario ``loc`` segments are contract-defined identifiers or list indices;
    no bracket-quoting is applied (we assume keys are valid Python identifiers).

    Strips discriminator-tag segments (e.g., ``"slow_copy_commit"``) and
    rewrites Python field aliases (e.g., ``for_`` → ``for``).

    >>> format_jsonpath(("timeline", 3, "target"))
    '$.timeline[3].target'
    >>> format_jsonpath(("timeline", 5, "slow_copy_commit", "for_"))
    '$.timeline[5].for'
    """
    cleaned: list[str | int] = []
    for segment in loc:
        if isinstance(segment, str) and segment in _DISCRIMINATOR_TAGS:
            continue
        if isinstance(segment, str) and segment in _ALIAS_REWRITES:
            cleaned.append(_ALIAS_REWRITES[segment])
        else:
            cleaned.append(segment)

    if not cleaned:
        return "$"
    parts = ["$"]
    for segment in cleaned:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}")
    return "".join(parts)
