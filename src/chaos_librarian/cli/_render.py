"""Human-readable rendering and small Typer-callback utilities shared by commands."""

from __future__ import annotations

from pathlib import Path

import typer

from chaos_librarian.validation import ValidationReport, ValidationSeverity

__all__ = ["render_human", "validate_new_out_path"]


_SEVERITY_LABEL = {
    ValidationSeverity.ERROR: "ERROR",
    ValidationSeverity.WARNING: "WARN ",
    ValidationSeverity.INFO: "INFO ",
}


def validate_new_out_path(value: Path) -> Path:
    """Reject --out paths that already exist or whose parent is not a writable directory."""
    if value.exists():
        raise typer.BadParameter(f"--out path already exists: {value}")
    parent = value.parent
    if not parent.exists():
        raise typer.BadParameter(f"--out parent directory does not exist: {parent}")
    if not parent.is_dir():
        raise typer.BadParameter(f"--out parent is not a directory: {parent}")
    return value


def render_human(report: ValidationReport) -> None:
    status = "OK" if report.ok else f"FAIL ({len(report.issues)} issues)"
    typer.echo(f"scenario: {report.scenario_id}")
    typer.echo(f"status: {status}")
    if not report.issues:
        return
    typer.echo("")
    for issue in report.issues:
        label = _SEVERITY_LABEL[issue.severity]
        location = (
            f"line {issue.line}:{issue.column}"
            if issue.line is not None and issue.column is not None
            else ""
        )
        path = issue.path or ""
        typer.echo(f"{label}  {issue.code:<25} {path:<35} {location:<14} {issue.message}")
