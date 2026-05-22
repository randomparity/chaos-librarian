"""Registers every command with the Typer ``app`` via import side effects.

The CLI contract pins the order in which ``chaos-librarian --help`` lists
commands, and ``typer`` renders that list in registration order. Each
import below fires one ``@app.command()`` decorator that appends to
``app.registered_commands``; reordering or removing any line is a public-
surface change. ``test_app.test_registered_commands_match_expected_order``
locks this contract mechanically.
"""

# ruff: noqa: F401, I001
# F401: command modules are imported for the decorator side effect only.
# I001: order is the CLI contract; alphabetizing would break --help output.
from __future__ import annotations

from chaos_librarian.cli.commands import validate
from chaos_librarian.cli.commands import plan
from chaos_librarian.cli.commands import materialize
from chaos_librarian.cli.commands import run
from chaos_librarian.cli.commands import step
from chaos_librarian.cli.commands import replay
from chaos_librarian.cli.commands import inspect
from chaos_librarian.cli.commands import capabilities
from chaos_librarian.cli.commands import clean
from chaos_librarian.cli.commands import compare
