"""Replay a run dir into per-journal-entry manifest snapshots.

The exporter re-runs the scenario through the same engine path as
``plan``/``replay`` (``build_initial_state`` → ``apply_event`` →
``to_manifest``), snapshotting after every journal entry, and cross-checks
the on-disk journal positionally on ``(event_id, action, phase)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.visualize.errors import JournalCorruptLineError

_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


@dataclass(frozen=True)
class ParsedJournal:
    """On-disk journal entries plus a torn-final-line marker.

    Attributes:
        entries: Successfully parsed entries, in file order.
        ended_mid_write: ``True`` when the final line was an incomplete
            (torn) write that was dropped — the expected shape of a still-
            running or crashed run.
    """

    entries: list[JournalEntry]
    ended_mid_write: bool


def parse_journal_text(text: str) -> ParsedJournal:
    """Parse journal.jsonl text, tolerating a torn final line.

    A final line that fails to parse is treated as the journal head (a torn
    write) and dropped with ``ended_mid_write=True``. Any *non-final*
    unparseable line is corruption and raises ``JournalCorruptLineError``.

    Args:
        text: Raw contents of ``journal.jsonl`` (may be empty).

    Returns:
        A :class:`ParsedJournal`.

    Raises:
        JournalCorruptLineError: a non-final line failed to parse.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    entries: list[JournalEntry] = []
    ended_mid_write = False
    for idx, line in enumerate(lines, start=1):
        try:
            entries.append(_JOURNAL_ADAPTER.validate_json(line))
        except ValidationError as exc:
            if idx == len(lines):
                ended_mid_write = True
                break
            raise JournalCorruptLineError(line=idx, detail=str(exc)) from exc
    return ParsedJournal(entries=entries, ended_mid_write=ended_mid_write)
