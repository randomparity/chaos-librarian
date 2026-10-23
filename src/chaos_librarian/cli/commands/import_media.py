"""``import`` command: scan an existing media library into a scenario bundle.

Issue #105 / ADR 0012. Exit codes follow ``docs/contract/cli-reference.md``:
0 success; 1 operational failure (``E_IMPORT_FAILED``); 2 usage
(``validate_new_out_path`` / ``typer.BadParameter``); 4 required external
tool missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import E_IMPORT_FAILED, emit_cli_error
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.importer.emit import (
    apply_work_caps,
    compute_staging,
    emit_import_bundle,
    plan_staging,
    validate_mapping_out,
)
from chaos_librarian.importer.probe_input import probe_inputs
from chaos_librarian.importer.scan import scan_directory
from chaos_librarian.importer.topology import attach_sidecars, build_topology
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities

_MODES = ("full", "sample", "dedup")


@app.command(name="import")
def import_media(
    input_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    mode: Annotated[str, typer.Option("--mode")] = "full",
    max_works: Annotated[int | None, typer.Option("--max-works")] = None,
    max_variants: Annotated[int, typer.Option("--max-variants")] = 4,
    max_duration_s: Annotated[float | None, typer.Option("--max-duration-s")] = None,
    mapping_out: Annotated[Path | None, typer.Option("--mapping-out")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Scan an existing media library and emit a scenario bundle."""
    if mode not in _MODES:
        raise typer.BadParameter(f"--mode must be one of {', '.join(_MODES)}")
    try:
        validate_mapping_out(input_dir, out, mapping_out)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    caps = detect_capabilities()
    if not caps.ffprobe.meets_minimum:
        emit_cli_error(
            error_code=E_IMPORT_FAILED,
            message="ffprobe is missing or below the minimum supported version",
            json_output=json_output,
        )
        raise typer.Exit(code=4)

    try:
        scanned, skips = scan_directory(input_dir)
        probed, probe_skips = probe_inputs([s for s in scanned if s.kind in {"video", "audio"}])
        sidecars = [s for s in scanned if s.kind not in {"video", "audio"}]
        skips.extend(probe_skips)

        accepted, all_skips = plan_staging(
            probed,
            skips,
            mode=mode,
            max_works=max_works,
            max_duration_s=max_duration_s,
        )
        works, topology_skips = build_topology(accepted, [], input_dir)
        all_skips.extend(topology_skips)
        apply_work_caps(
            works,
            all_skips,
            mode=mode,
            max_works=max_works,
            max_variants=max_variants,
        )
        attach_sidecars(works, sidecars, all_skips)
        if not works:
            emit_cli_error(
                error_code=E_IMPORT_FAILED,
                message="no importable media found",
                json_output=json_output,
            )
            raise typer.Exit(code=1)

        staged, _referenced = compute_staging(accepted, works)
        report = emit_import_bundle(
            input_dir, out, works, staged, all_skips, mapping_out=mapping_out
        )
    except typer.Exit:
        raise
    except Exception as exc:
        emit_cli_error(
            error_code=E_IMPORT_FAILED,
            message=f"{type(exc).__name__}: {exc}",
            json_output=json_output,
        )
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps(report.as_dict(), indent=2))
    else:
        typer.echo(
            f"import: wrote {out} ({report.files_imported} assets, "
            f"{len(report.files_skipped)} skipped)"
        )
