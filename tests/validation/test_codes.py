"""Tests for validation.codes: constants, Pydantic map, JSONPath formatter."""

from __future__ import annotations

import pytest

from chaos_librarian.validation import codes


class TestPydanticToCode:
    """Pydantic error types map to stable chaos-librarian E_* codes.

    WHY: the public code set is a contract for downstream tooling (voom-v2,
    CI green/red dashboards). Renaming a code is a breaking change.
    """

    @pytest.mark.parametrize(
        ("pydantic_type", "expected_code"),
        [
            ("missing", "E_FIELD_MISSING"),
            ("extra_forbidden", "E_FIELD_UNKNOWN"),
            ("literal_error", "E_FIELD_LITERAL"),
            ("string_type", "E_FIELD_TYPE"),
            ("int_type", "E_FIELD_TYPE"),
            ("list_type", "E_FIELD_TYPE"),
            ("dict_type", "E_FIELD_TYPE"),
            ("union_tag_invalid", "E_TIMELINE_ACTION_UNKNOWN"),
            ("union_tag_not_found", "E_TIMELINE_ACTION_UNKNOWN"),
        ],
    )
    def test_known_pydantic_types_map(self, pydantic_type: str, expected_code: str) -> None:
        assert codes.PYDANTIC_TO_CODE[pydantic_type] == expected_code

    def test_unmapped_type_absent_from_map(self) -> None:
        """Unmapped types must not be in the dict (caller falls back to E_FIELD_SHAPE)."""
        assert "made_up_type" not in codes.PYDANTIC_TO_CODE


class TestFormatJSONPath:
    """Loc tuples convert to JSONPath strings, stripping discriminator tags.

    WHY: scenario authors read the path in the report to find the field;
    the discriminator tag (e.g., "slow_copy_commit") is a Pydantic
    internal, not a YAML key, and would mislead them.
    """

    def test_root_loc(self) -> None:
        assert codes.format_jsonpath(()) == "$"

    def test_simple_field(self) -> None:
        assert codes.format_jsonpath(("scenario_id",)) == "$.scenario_id"

    def test_nested(self) -> None:
        assert codes.format_jsonpath(("timeline", 3, "target")) == "$.timeline[3].target"

    def test_deep_nested(self) -> None:
        assert (
            codes.format_jsonpath(("movies", 0, "variants", 1, "bundle", "assets", 2, "id"))
            == "$.movies[0].variants[1].bundle.assets[2].id"
        )

    def test_discriminator_tag_stripped(self) -> None:
        """Pydantic inserts the resolved discriminator value mid-loc; strip it."""
        loc = ("timeline", 5, "slow_copy_commit", "for_")
        # tag stripped; alias for_ → for applied
        assert codes.format_jsonpath(loc) == "$.timeline[5].for"

    def test_all_discriminator_tags_stripped(self) -> None:
        for tag in (
            "move_asset",
            "rename_file",
            "delete_file",
            "add_file",
            "reencode_video",
            "reencode_audio",
            "create_sidecar",
            "slow_copy_start",
            "slow_copy_commit",
        ):
            assert codes.format_jsonpath(("timeline", 0, tag, "target")) == "$.timeline[0].target"

    def test_for_alias_rewrite_without_tag(self) -> None:
        """Even if Pydantic ever omits the tag, the for_ → for alias still applies."""
        assert codes.format_jsonpath(("timeline", 5, "for_")) == "$.timeline[5].for"


class TestCodeConstants:
    """All E_* codes referenced by the spec are defined as constants.

    WHY: rules and tests refer to constants, not string literals, so a
    code rename is a single-file change.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "E_YAML_PARSE",
            "E_TOP_LEVEL_NOT_MAPPING",
            "E_FIELD_MISSING",
            "E_FIELD_UNKNOWN",
            "E_FIELD_LITERAL",
            "E_FIELD_TYPE",
            "E_FIELD_SHAPE",
            "E_TIMELINE_ACTION_UNKNOWN",
            "E_DURATION_SYNTAX",
            "E_ID_DUPLICATE",
            "E_TARGET_UNKNOWN",
            "E_SLOW_COPY_UNPAIRED",
            "E_SLOW_COPY_TIMING",
            "E_PATH_CONTAINMENT",
            "E_PATH_DUPLICATE",
            "E_TIMELINE_ORDER",
            "E_SIDECAR_TARGET_UNKNOWN",
            "E_EXTRACT_TRACK_UNKNOWN",
            "E_SIDECAR_KIND_MISMATCH",
            "E_SIDECAR_PATH_COLLISION",
            "E_PROFILE_REQUIRED",
            "E_PROFILE_BUDGET_EXCEEDED",
            "E_MATERIALIZE_UNSUPPORTED",
        ],
    )
    def test_constant_defined(self, name: str) -> None:
        assert getattr(codes, name) == name
