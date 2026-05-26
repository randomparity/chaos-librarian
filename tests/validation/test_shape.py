"""Tests for validation.shape: Pydantic ValidationError → ValidationIssue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import RunInput, codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.shape import run_shape_pass


def _run_input_from_dict(raw: dict[str, Any]) -> RunInput:
    """Build a RunInput around a raw dict, skipping YAML re-parse.

    Shape-pass tests exercise dict→ValidationError mapping; the raw bytes
    and line index aren't relevant to that contract.
    """
    return RunInput(
        path=Path("memory:test"),
        raw_bytes=b"",
        content_hash="",
        raw_data=raw,
        line_index=LineIndex(),
    )


class TestShapePassMissingFields:
    """Pydantic 'missing' → E_FIELD_MISSING.

    WHY: the spec freezes scenario_id, schema_version, etc. as required;
    omitting one must surface as a clear, named issue.
    """

    def test_missing_scenario_id(self) -> None:
        raw = {"schema_version": 2}  # minimal — many fields missing
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        codes_emitted = {i.code for i in collector.issues}
        assert codes.E_FIELD_MISSING in codes_emitted


class TestShapePassUnknownField:
    """Pydantic 'extra_forbidden' → E_FIELD_UNKNOWN.

    WHY: ConfigDict(extra="forbid") on every model catches typos that
    would otherwise silently no-op; the code surfaces that to authors.
    """

    def test_unknown_top_level_field(self) -> None:
        raw = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "movies": [],
            "series": [],
            "artists": [],
            "timeline": [],
            "made_up_extra_field": 1,
        }
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        assert any(i.code == codes.E_FIELD_UNKNOWN for i in collector.issues)


class TestShapePassLiteralValue:
    """Pydantic 'literal_error' → E_FIELD_LITERAL.

    WHY: duration_scale and schema_version are closed enums; an
    out-of-range value should be cleanly named.
    """

    def test_wrong_duration_scale(self) -> None:
        raw = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "extremely_long",  # not in Literal
            "library": {"roots": []},
            "movies": [],
            "series": [],
            "artists": [],
            "timeline": [],
        }
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        assert any(i.code == codes.E_FIELD_LITERAL for i in collector.issues)

    def test_unknown_video_color_space(self) -> None:
        raw = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "root_main", "path": "library"}]},
            "movies": [
                {
                    "id": "movie_color",
                    "title": "Color",
                    "layout": "movie_flat",
                    "variants": [
                        {
                            "id": "variant_main",
                            "label": "main",
                            "bundle": {
                                "id": "bundle_main",
                                "assets": [
                                    {
                                        "id": "asset_main",
                                        "role": "main",
                                        "container": "mkv",
                                        "duration_seconds": 1.0,
                                        "video": {
                                            "source": "color_bars",
                                            "codec": "h264",
                                            "resolution": "sd",
                                            "color_space": "ntsc_j",
                                        },
                                        "audio": [],
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "series": [],
            "artists": [],
            "timeline": [],
        }
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)

        assert any(
            issue.code == codes.E_FIELD_LITERAL
            and issue.path is not None
            and issue.path.endswith(".video.color_space")
            for issue in collector.issues
        )


class TestShapePassDiscriminatorTag:
    """Pydantic 'union_tag_invalid' → E_TIMELINE_ACTION_UNKNOWN.

    WHY: a typo in a timeline event's `action:` value (e.g., `move_assets`
    instead of `move_asset`) is the most common authoring mistake;
    flagging it with a specific code keeps the message readable.
    """

    def test_unknown_action(self) -> None:
        raw = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "movies": [],
            "series": [],
            "artists": [],
            "timeline": [
                {"id": "e1", "at": "1s", "action": "bogus_action", "target": "x"},
            ],
        }
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        assert any(i.code == codes.E_TIMELINE_ACTION_UNKNOWN for i in collector.issues)


class TestShapePassJSONPathStripping:
    """A discriminator tag in the Pydantic loc must not appear in the JSONPath.

    WHY: the discriminator tag is an internal Pydantic detail and would
    mislead an author looking for a field named "slow_copy_commit" in
    their YAML.
    """

    def test_for_alias_under_slow_copy_commit(self) -> None:
        raw = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "movies": [],
            "series": [],
            "artists": [],
            "timeline": [
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "slow_copy_commit",
                    "for": 12345,  # wrong type — for must be str
                },
            ],
        }
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        paths = [i.path for i in collector.issues if i.path]
        assert all("slow_copy_commit" not in p for p in paths)
        # Discriminator tag 'slow_copy_commit' is stripped, leaving 'for' intact.
        assert any(p == "$.timeline[0].for" for p in paths)


class TestShapePassTupleType:
    """Pydantic 'tuple_type' → E_FIELD_TYPE.

    WHY: Scenario collection fields (``library.roots``, ``movies``,
    ``series``, ``artists``,
    ``timeline``, etc.) are ``tuple[X, ...]`` so the cached parse can't be
    mutated via list methods. A non-sequence value supplied for one of
    these fields surfaces as Pydantic ``tuple_type`` and must map to the
    same stable ``E_FIELD_TYPE`` contract that ``list_type`` does;
    otherwise the change from list to tuple would silently regress the
    public error-code contract to ``E_FIELD_SHAPE``.
    """

    @pytest.mark.parametrize(
        ("mutation_path", "bad_value"),
        [
            (("library", "roots"), {}),
            (("movies",), {}),
            (("series",), {}),
            (("artists",), {}),
            (("timeline",), "not-a-sequence"),
        ],
    )
    def test_non_sequence_for_collection_field_emits_field_type(
        self,
        mutation_path: tuple[str, ...],
        bad_value: object,
    ) -> None:
        raw: dict[str, Any] = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "movies": [],
            "series": [],
            "artists": [],
            "timeline": [],
        }
        target = raw
        for key in mutation_path[:-1]:
            target = target[key]
        target[mutation_path[-1]] = bad_value
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        assert any(i.code == codes.E_FIELD_TYPE for i in collector.issues), (
            f"expected E_FIELD_TYPE at {mutation_path!r}, got {[i.code for i in collector.issues]}"
        )


class TestShapePassNoErrorsForValidScenario:
    """A valid raw dict produces zero issues from the shape pass.

    WHY: this is the contract; downstream semantic rules can assume
    no shape-level noise was injected for valid input.
    """

    def test_valid_scenario_produces_no_issues(self) -> None:
        raw = {
            "schema_version": 15,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r", "path": "r"}]},
            "movies": [],
            "series": [],
            "artists": [],
            "timeline": [],
        }
        collector = IssueCollector()
        run_shape_pass(_run_input_from_dict(raw), collector)
        assert collector.issues == []
