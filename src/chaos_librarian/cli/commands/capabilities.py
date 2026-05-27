"""``capabilities`` command: probe ffmpeg/ffprobe/mkvtoolnix and report status."""

from __future__ import annotations

from typing import Annotated

import typer

from chaos_librarian.cli.app import app
from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.materializer import detect_capabilities


@app.command()
def capabilities(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Detect available media tools (ffmpeg, ffprobe, mkvtoolnix)."""
    caps = detect_capabilities()
    if json_output:
        typer.echo(caps.model_dump_json(indent=2, exclude_none=True))
    else:
        _render_capabilities_human(caps)
    exit_code = 0 if (caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum) else 4
    raise typer.Exit(code=exit_code)


def _render_capabilities_human(caps: Capabilities) -> None:
    """Echo the capabilities payload as a plain key:value block to stdout."""
    typer.echo(f"platform:   {caps.platform}")
    for name, tool in (
        ("ffmpeg", caps.ffmpeg),
        ("ffprobe", caps.ffprobe),
        ("mkvtoolnix", caps.mkvtoolnix),
    ):
        if not tool.found:
            typer.echo(f"  {name:<11} missing")
            continue
        status = "OK" if tool.meets_minimum else "BELOW MINIMUM"
        typer.echo(f"  {name:<11} {tool.version} ({tool.path}) [{status}]")
    typer.echo("ready_for:")
    typer.echo(f"  materialize_static:               {caps.ready_for.materialize_static}")
    typer.echo(
        f"  materialize_filesystem_mutations: {caps.ready_for.materialize_filesystem_mutations}"
    )
    typer.echo(f"  materialize_media_mutations:      {caps.ready_for.materialize_media_mutations}")
    typer.echo(f"  materialize_hevc_video:          {caps.ready_for.materialize_hevc_video}")
    typer.echo(f"  materialize_hdr_video:           {caps.ready_for.materialize_hdr_video}")
    typer.echo(
        "  materialize_resolution_switch_video: "
        f"{caps.ready_for.materialize_resolution_switch_video}"
    )
    typer.echo("content_sources:")
    for provider in caps.content_sources.providers:
        status = "OK" if provider.available else "UNAVAILABLE"
        suffix = f" ({provider.reason})" if provider.reason else ""
        typer.echo(f"  {provider.name:<16} [{status}]{suffix}")
        typer.echo(f"    requires_network: {provider.requires_network}")
        typer.echo(f"    requires_cache:   {provider.requires_cache}")
        if provider.required_tool is not None:
            typer.echo(f"    required_tool:    {provider.required_tool}")
        if provider.cache_dir is not None:
            typer.echo(f"    cache_dir:        {provider.cache_dir}")
        if provider.cache_writable is not None:
            typer.echo(f"    cache_writable:   {provider.cache_writable}")
        if provider.sources:
            typer.echo(f"    sources:          {', '.join(provider.sources)}")
