"""Tests for the unified CLI error envelope (issue #15).

The envelope policy is one shape for every command:
- JSON key ``error_code`` (not ``error``)
- Output stream is stderr (both JSON and human)
- Human format is multi-line: ``chaos-librarian: failed (CODE)`` followed
  by indented key/value rows
- Per-exception ``payload`` content is nested under a ``details`` key so it
  cannot collide with the structured top-level fields
  (``error_code``, ``message``, ``asset_id``, ``field``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli import app as app_mod
from chaos_librarian.cli.app import app
from chaos_librarian.materializer import (
    MaterializeArtifacts,
    UnsupportedMaterializationError,
)

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "scenarios"

runner = CliRunner()


def _materialize_with_unsupported_codec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    json_output: bool,
) -> tuple[int, str, str]:
    """Run materialize with an injected ``UnsupportedMaterializationError``.

    Returns ``(exit_code, stdout, stderr)``. ``UnsupportedMaterializationError``
    has every interesting envelope field populated (``asset_id``, ``field``,
    ``payload``) so a single fixture covers the full envelope contract.
    """

    def raise_unsupported(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise UnsupportedMaterializationError(
            "opus not supported",
            asset_id="a0",
            field="audio[0].codec",
            payload={"supported": ["aac"]},
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_unsupported)
    out = tmp_path / "absent"
    args = ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)]
    if json_output:
        args.append("--json")
    result = runner.invoke(app, args)
    return result.exit_code, result.stdout, result.stderr


class TestUnifiedEnvelopeJsonShape:
    """JSON envelope: ``error_code`` (not ``error``), stderr stream, details nested.

    WHY: downstream agents (voom-v2) parse the JSON; a single canonical key
    + stream is the contract that lets them avoid per-command branching.
    """

    def test_uses_error_code_key_not_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        code, _stdout, stderr = _materialize_with_unsupported_codec(
            monkeypatch, tmp_path, json_output=True
        )
        assert code == 5
        payload = json.loads(stderr)
        assert "error_code" in payload
        assert payload["error_code"] == "E_MATERIALIZE_UNSUPPORTED"
        assert "error" not in payload, "legacy `error` key must be removed"

    def test_json_envelope_goes_to_stderr_not_stdout(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        code, stdout, stderr = _materialize_with_unsupported_codec(
            monkeypatch, tmp_path, json_output=True
        )
        assert code == 5
        assert stdout == "", f"stdout should be empty for errors, got: {stdout!r}"
        assert stderr.strip(), "stderr should carry the JSON envelope"

    def test_payload_nests_under_details(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """``exc.payload`` content must live under ``details`` so it can't
        collide with the top-level structured fields."""
        _code, _stdout, stderr = _materialize_with_unsupported_codec(
            monkeypatch, tmp_path, json_output=True
        )
        payload = json.loads(stderr)
        assert "details" in payload, f"expected details key, got {payload.keys()}"
        assert payload["details"] == {"supported": ["aac"]}
        # And nothing leaks to top level.
        assert "supported" not in payload, (
            "exc.payload fields must NOT be shallow-merged into the top level"
        )


class TestUnifiedEnvelopeHumanFormat:
    """Human format: multi-line ``chaos-librarian: failed (CODE)`` + rows.

    WHY: a single human format means operators see the same shape for every
    failure regardless of which command failed.
    """

    def test_human_format_multiline_to_stderr(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        code, stdout, stderr = _materialize_with_unsupported_codec(
            monkeypatch, tmp_path, json_output=False
        )
        assert code == 5
        assert stdout == "", "human-format errors must not write to stdout"
        # Banner is the unified shape, not the old per-command "materialize failed".
        assert "chaos-librarian: failed (E_MATERIALIZE_UNSUPPORTED)" in stderr
        # Structured rows are indented.
        assert "  message:" in stderr
        assert "  asset:" in stderr
        assert "  field:" in stderr


class TestMaterializeOnUnparseableYaml:
    """Materialize on unparseable YAML routes through the envelope.

    WHY: ``materialize_scenario`` calls ``prepare_run_input`` which raises
    ``ScenarioLoadError`` for unreadable files or invalid YAML. Without an
    explicit catch in the CLI handler the exception escapes Typer and the
    caller gets a raw traceback instead of an ``error_code`` envelope.
    """

    def test_invalid_yaml_emits_unified_envelope(self, tmp_path: Path) -> None:
        scenario = tmp_path / "broken.yaml"
        scenario.write_text("key: : value\n")  # invalid YAML
        out = tmp_path / "absent"
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out), "--json"])
        assert result.exit_code == 3
        payload = json.loads(result.stderr)
        assert payload["error_code"] == "E_YAML_PARSE"
        assert payload["scenario_path"] == str(scenario)


class TestReplayBundleParseFailure:
    """A malformed replay bundle must route through the unified envelope.

    WHY: ``_REPLAY_BUNDLE_ADAPTER.validate_json`` runs before any of the
    command's structured error paths. If it raises an unguarded
    ``ValidationError``, a downstream agent gets no ``error_code`` JSON
    and no exit-code-mapped envelope — just a raw exception traceback
    from typer's default exception handler. The replay command catches
    this and emits ``replay_bundle_invalid`` so the contract holds.
    """

    def test_malformed_bundle_emits_unified_envelope(self, tmp_path: Path) -> None:
        bundle_path = tmp_path / "bad.json"
        bundle_path.write_bytes(b"")
        out = tmp_path / "out"
        result = runner.invoke(app, ["replay", str(bundle_path), "--out", str(out), "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stderr)
        assert payload["error_code"] == "replay_bundle_invalid"
        assert payload["bundle_path"] == str(bundle_path)


class TestValidationReportCarveOut:
    """``validate --json`` and ``plan --json`` are exempt from the envelope.

    WHY: a failing validation emits a ``ValidationReport`` (with ``ok: false``),
    not an error envelope. The report describes the scenario, not the
    command's failure — agents that ask for ``--json`` from these commands
    want the report. This test pins the carve-out so a future "unify
    everything" refactor cannot silently break the contract that downstream
    agents key on (``ok`` field, ``issues`` array, on stdout).
    """

    def test_validate_failure_json_writes_report_to_stdout(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("not a mapping at the top level\n")
        result = runner.invoke(app, ["validate", str(bad), "--json"])
        assert result.exit_code == 3
        report = json.loads(result.stdout)
        assert report["ok"] is False
        assert "issues" in report
        # No error envelope on stderr — this is a report, not an error.
        assert "error_code" not in result.stdout
        assert result.stderr == ""

    def test_plan_failure_json_writes_report_to_stdout(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("not a mapping at the top level\n")
        out = tmp_path / "absent"
        result = runner.invoke(app, ["plan", str(bad), "--out", str(out), "--json"])
        assert result.exit_code == 3
        report = json.loads(result.stdout)
        assert report["ok"] is False
        assert result.stderr == ""


class TestStepCommandUsesUnifiedEnvelope:
    """The step command now emits the same envelope as materialize.

    WHY: the original ``_emit_step_error`` used a ``"error"`` key, single-line
    human format, and stderr. Unifying it means every command's failure
    record has the same key.
    """

    def test_step_sentinel_error_uses_error_code_key(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "no-sentinel"
        run_dir.mkdir()
        result = runner.invoke(app, ["step", str(run_dir), "--json"])
        assert result.exit_code == 7
        payload = json.loads(result.stderr)
        assert "error_code" in payload, f"step must use error_code key, got {list(payload.keys())}"
        assert "error" not in payload
