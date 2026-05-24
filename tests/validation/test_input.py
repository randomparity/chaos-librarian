"""Tests for chaos_librarian.validation.input."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.engine import run_plan
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import (
    RunInput,
    codes,
    prepare_run_input,
    prepare_run_input_from_bytes,
    run_validation,
)


class TestPrepareRunInput:
    """The factory binds raw bytes, hash, and parsed data in one record.

    WHY: validation, planning, and replay-bundle embedding must all describe
    the same byte sequence — otherwise ``validation.json`` can vouch for one
    payload while ``replay.json`` carries another. A single immutable read
    is the cheapest way to guarantee that.
    """

    def test_content_hash_matches_sha256_of_file(self, tmp_path: Path) -> None:
        path = tmp_path / "s.yaml"
        path.write_bytes(b"schema_version: 1\nscenario_id: s\nseed: 1\n")
        run_input = prepare_run_input(path)
        assert isinstance(run_input, RunInput)
        assert run_input.raw_bytes == path.read_bytes()
        assert run_input.content_hash == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_from_bytes_matches_from_path(self, tmp_path: Path) -> None:
        payload = b"schema_version: 1\nscenario_id: s\nseed: 1\n"
        path = tmp_path / "s.yaml"
        path.write_bytes(payload)
        a = prepare_run_input(path)
        b = prepare_run_input_from_bytes(raw_bytes=payload, source_label="memory:s")
        assert a.raw_data == b.raw_data
        assert a.content_hash == b.content_hash

    def test_yaml_parse_error_raises_from_factory(self, tmp_path: Path) -> None:
        """``ScenarioLoadError`` must surface from the factory, never inside
        ``run_validation`` — otherwise an upstream caller could skip the
        factory and bypass the byte-binding guarantee."""
        path = tmp_path / "broken.yaml"
        path.write_text("key: : value\n")  # invalid YAML
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(path)

    def test_missing_file_raises_from_factory(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(tmp_path / "missing.yaml")


class TestRunInputScenarioCache:
    """``RunInput.scenario`` parses the Scenario once and caches the result.

    WHY: ``materialize_scenario``, ``run_validation`` (shape pass), and
    ``run_plan`` previously each called ``Scenario.model_validate`` on the
    same ``raw_data``. Caching on RunInput makes "one read = one parse"
    structurally enforced — every consumer that holds the same RunInput
    receives the same parsed object identity.
    """

    _VALID_BYTES = (
        b"schema_version: 9\n"
        b"scenario_id: s1\n"
        b"seed: 1\n"
        b"duration_scale: short\n"
        b"library:\n"
        b"  roots:\n"
        b"    - id: r\n"
        b"      path: r\n"
        b"works: []\n"
        b"timeline: []\n"
    )

    def test_scenario_returns_parsed_scenario(self, tmp_path: Path) -> None:
        path = tmp_path / "s.yaml"
        path.write_bytes(self._VALID_BYTES)
        run_input = prepare_run_input(path)
        assert isinstance(run_input.scenario, Scenario)
        assert run_input.scenario.scenario_id == "s1"

    def test_scenario_is_cached_across_accesses(self, tmp_path: Path) -> None:
        """Second access must return the SAME object (identity, not equality).

        Identity is the only test that distinguishes "cached" from "re-parsed
        and happens to be equal" — Scenario.model_validate is deterministic
        on the same bytes, so equality alone would not prove caching.
        """
        path = tmp_path / "s.yaml"
        path.write_bytes(self._VALID_BYTES)
        run_input = prepare_run_input(path)
        first = run_input.scenario
        second = run_input.scenario
        assert first is second

    def test_scenario_raises_validation_error_on_invalid_shape(self, tmp_path: Path) -> None:
        """Access against a shape-invalid scenario raises ValidationError.

        The validation pipeline's shape pass catches this exception and
        converts it to structured issues; callers downstream of a passing
        validation report must be able to assume the property succeeds.
        """
        path = tmp_path / "broken.yaml"
        # Missing required scenario_id, seed
        path.write_bytes(b"schema_version: 1\n")
        run_input = prepare_run_input(path)
        with pytest.raises(ValidationError):
            _ = run_input.scenario

    def test_cached_scenario_is_frozen_against_attribute_reassignment(
        self,
        tmp_path: Path,
    ) -> None:
        """Top-level attribute reassignment on the cached Scenario must raise.

        WHY: ``RunInput.scenario`` is shared across the validation pipeline,
        ``run_plan``, ``replay_plan_bundle``, and ``materialize_scenario``.
        A reassignment between validation and the engine would silently make
        the engine's output disagree with ``raw_bytes`` (which is what the
        replay bundle records). Every model under Scenario is
        ``frozen=True`` to catch reassignment at the type-system level.
        """
        path = tmp_path / "s.yaml"
        path.write_bytes(self._VALID_BYTES)
        run_input = prepare_run_input(path)
        with pytest.raises(ValidationError):
            run_input.scenario.scenario_id = "tampered"  # type: ignore[misc]

    def test_cached_scenario_subtree_is_deeply_immutable(
        self,
        tmp_path: Path,
    ) -> None:
        """Nested attribute and collection mutation on the cached Scenario
        must also raise.

        WHY: top-level ``frozen=True`` alone would let
        ``scenario.library.roots[0].path = "tampered"`` or
        ``scenario.works.append(...)`` slip through and desync engine output
        from ``raw_bytes``. The contract makes every sub-model
        ``frozen=True`` and every collection field ``tuple[X, ...]`` so
        both forms of nested mutation raise.
        """
        path = tmp_path / "s.yaml"
        path.write_bytes(self._VALID_BYTES)
        run_input = prepare_run_input(path)

        # 1. Nested attribute reassignment on a sub-model.
        with pytest.raises(ValidationError):
            run_input.scenario.library.roots[0].path = "tampered"  # type: ignore[misc]
        # 2. Collection fields are tuples — immutable by Python contract.
        # ``isinstance(..., tuple)`` is the structural assertion; the
        # follow-up ``hasattr`` check confirms list mutators are absent.
        assert isinstance(run_input.scenario.library.roots, tuple)
        assert isinstance(run_input.scenario.works, tuple)
        assert isinstance(run_input.scenario.timeline, tuple)
        assert not hasattr(run_input.scenario.works, "append")

    def test_validation_invalidates_stale_cache_after_raw_data_mutation(
        self,
        tmp_path: Path,
    ) -> None:
        """A stale cache from pre-validation access must not bypass shape errors.

        WHY: if a caller accesses ``run_input.scenario`` first (populating
        the cache), then mutates ``run_input.raw_data`` to shape-invalid
        content, the shape pass must still catch the mutation. The pass
        parses ``raw_data`` directly and primes the cache from that fresh
        parse, so a stale cache cannot silently produce ``ok=True``.
        """
        path = tmp_path / "s.yaml"
        path.write_bytes(self._VALID_BYTES)
        run_input = prepare_run_input(path)

        # Step 1: pre-populate the cache via direct property access.
        assert isinstance(run_input.scenario, Scenario)

        # Step 2: mutate raw_data to a shape-invalid value (works must be a list).
        run_input.raw_data["works"] = {}

        # Step 3: validation must catch the mutation, not return the stale parse.
        report = run_validation(run_input)
        assert report.ok is False
        assert any(i.code == codes.E_FIELD_TYPE for i in report.issues), (
            f"expected E_FIELD_TYPE issue, got {[i.code for i in report.issues]}"
        )

    def test_validate_and_plan_parse_scenario_once(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A full validate→plan cycle calls Scenario.model_validate exactly once.

        WHY: this is the dedup contract from issue #14. The cached_property is
        the single parse site; both ``run_shape_pass`` and ``run_plan`` must
        route through it instead of re-parsing.
        """
        path = tmp_path / "s.yaml"
        path.write_text(
            "schema_version: 9\n"
            "scenario_id: dedup\n"
            "seed: 1\n"
            "duration_scale: short\n"
            "library:\n"
            "  roots:\n"
            "    - id: r\n"
            "      path: r\n"
            "works: []\n"
            "timeline: []\n",
        )

        original = Scenario.model_validate
        counter = {"calls": 0}

        def counting(*args: Any, **kwargs: Any) -> Scenario:
            counter["calls"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(Scenario, "model_validate", counting)

        run_input = prepare_run_input(path)
        report = run_validation(run_input)
        assert report.ok is True
        run_plan(run_input=run_input, validation_report=report, steps_limit=None)

        assert counter["calls"] == 1
