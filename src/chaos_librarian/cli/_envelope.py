"""Unified CLI error envelope (issue #15).

Every command emits failures via :func:`emit_cli_error` so downstream
agents key off a single ``{"error_code": ..., "message": ...}`` JSON shape.
``emit_materialize_error`` adapts the materializer's structured error
hierarchy to that envelope; ``synthesize_yaml_parse_report`` wraps an
unparseable scenario as the ``E_YAML_PARSE`` validation report (used by
``validate``, ``plan``, and ``materialize``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import typer

from chaos_librarian.cli._render import render_human
from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.materializer.errors import MaterializationError
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import ValidationReport, ValidationSeverity
from chaos_librarian.validation.codes import E_YAML_PARSE

__all__ = [
    "E_FIXTURE_INCONSISTENT",
    "E_JOURNAL_CORRUPT",
    "E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED",
    "E_REPLAY_BUNDLE_INVALID",
    "E_REPLAY_DIVERGENCE",
    "E_SCENARIO_TAMPERED",
    "E_SENTINEL_INVALID",
    "E_SENTINEL_IN_PROGRESS",
    "emit_cli_error",
    "emit_failure",
    "emit_materialize_error",
    "synthesize_yaml_parse_report",
]


# CLI envelope error codes (single shared vocabulary; spec-anchored E_* prefix).
# Materializer subclasses contribute their own E_MATERIALIZE_* codes via
# MaterializationError.error_code; validation contributes E_* codes via
# validation.codes. The constants below cover step/replay/clean/inspect paths.
E_SENTINEL_INVALID: Final = "E_SENTINEL_INVALID"
E_SENTINEL_IN_PROGRESS: Final = "E_SENTINEL_IN_PROGRESS"
E_SCENARIO_TAMPERED: Final = "E_SCENARIO_TAMPERED"
E_JOURNAL_CORRUPT: Final = "E_JOURNAL_CORRUPT"
E_REPLAY_BUNDLE_INVALID: Final = "E_REPLAY_BUNDLE_INVALID"
E_REPLAY_DIVERGENCE: Final = "E_REPLAY_DIVERGENCE"
E_FIXTURE_INCONSISTENT: Final = "E_FIXTURE_INCONSISTENT"
E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED: Final = "E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED"


def emit_cli_error(
    *,
    error_code: str,
    message: str,
    json_output: bool,
    asset_id: str | None = None,
    field: str | None = None,
    extra_top_level: dict[str, object] | None = None,
    details: dict[str, object] | None = None,
) -> None:
    """Single error envelope for every command (issue #15).

    Shape: ``error_code`` + ``message`` (always present), ``asset_id`` /
    ``field`` when applicable, ``extra_top_level`` for adjunct paths
    (e.g. ``materialization_report_path``), and ``details`` carrying the
    originating exception's payload. Both JSON and human-format output
    are written to stderr.

    Carve-out: ``validate --json`` and ``plan --json`` on a shape-invalid
    scenario emit a ``ValidationReport`` (with ``ok: false``) on stdout
    rather than this envelope. The report is structured output describing
    the scenario, not a message about an error condition — agents that
    request ``--json`` from those commands are asking for the report,
    not the envelope. Every other failure path on every command routes
    through here.
    """
    if json_output:
        payload: dict[str, object] = {
            "error_code": error_code,
            "message": message,
        }
        if asset_id is not None:
            payload["asset_id"] = asset_id
        if field is not None:
            payload["field"] = field
        if extra_top_level:
            payload.update(extra_top_level)
        if details:
            payload["details"] = details
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
        return
    typer.echo(f"chaos-librarian: failed ({error_code})", err=True)
    typer.echo(f"  message: {message}", err=True)
    if asset_id is not None:
        typer.echo(f"  asset:   {asset_id}", err=True)
    if field is not None:
        typer.echo(f"  field:   {field}", err=True)
    if extra_top_level:
        for key in sorted(extra_top_level):
            typer.echo(f"  {key}: {extra_top_level[key]}", err=True)
    if details:
        for key in sorted(details):
            typer.echo(f"  {key}: {details[key]}", err=True)


def emit_materialize_error(
    exc: MaterializationError,
    *,
    json_output: bool,
    run_dir: Path | None,
) -> None:
    extra: dict[str, object] | None = None
    if run_dir is not None:
        extra = {"materialization_report_path": str(run_dir / "materialization.json")}
    emit_cli_error(
        error_code=exc.error_code,
        message=exc.message,
        json_output=json_output,
        asset_id=exc.asset_id,
        field=exc.field,
        extra_top_level=extra,
        details=dict(exc.payload) if exc.payload else None,
    )


def emit_failure(report: ValidationReport, *, json_output: bool) -> None:
    """Emit a failed validation report through the validate/plan stdout path."""
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        render_human(report)


def synthesize_yaml_parse_report(scenario_path: Path, exc: ScenarioLoadError) -> ValidationReport:
    """Wrap a ScenarioLoadError as the E_YAML_PARSE validation report.

    The byte-binding factory raises now; the CLI maps the exception to
    the structured report shape promised for unparseable input.
    """
    return ValidationReport(
        schema_version=1,
        scenario_id="<unknown>",
        ok=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code=E_YAML_PARSE,
                message=str(exc),
                line=exc.line,
                column=exc.column,
                path=None,
            )
        ],
    )
