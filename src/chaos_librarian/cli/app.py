"""Typer app exposing the chaos-librarian CLI surface.

The :data:`app` is defined here; each command lives in its own module
under ``cli/commands/`` and registers itself via ``@app.command()`` at
import time. ``cli/commands/__init__.py`` imports the command modules in
the order ``--help`` should list them (the CLI contract pins that order).

See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="chaos-librarian",
    help="Scenario-driven synthetic media library simulator.",
    no_args_is_help=True,
)


# Import at the bottom (after ``app`` is constructed) so each command
# module's ``@app.command()`` decorator finds the live ``app`` object.
# ``noqa: E402`` because the top-of-module convention conflicts with the
# registration ordering.
import chaos_librarian.cli.commands  # noqa: E402, F401
