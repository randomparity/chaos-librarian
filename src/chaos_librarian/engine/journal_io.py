"""Canonical byte form of the journal.

``serialize_journal_bytes`` is shared between the on-disk writer (which
emits ``journal.jsonl``) and ``engine.plan.run_plan`` (which feeds the
same bytes into the ``journal_digest`` SHA-256 in the replay bundle).
Centralising the format here prevents the two byte streams from drifting
silently.
"""

from __future__ import annotations

from collections.abc import Iterable

from chaos_librarian.contract.journal import JournalEntry


def serialize_journal_bytes(entries: Iterable[JournalEntry]) -> bytes:
    """Canonical on-disk byte representation of a journal.

    Each entry serialises to one ``model_dump_json(by_alias=True,
    exclude_none=True)`` line followed by ``"\\n"``; an empty iterable
    yields ``b""``.
    """
    chunks: list[bytes] = []
    for entry in entries:
        line = entry.model_dump_json(by_alias=True, exclude_none=True)
        chunks.append(line.encode("utf-8"))
        chunks.append(b"\n")
    return b"".join(chunks)
