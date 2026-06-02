"""Shared accessors for network-lag journal ``state_delta`` fields.

wall_clock and replay both read the same network-lag fields off a journal
entry's ``state_delta`` with identical validation, differing only in the
exception type they raise. The accessor logic lives here once, parameterized
by ``error_type``; each caller binds its own exception type.
"""

from __future__ import annotations

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.scenario import NetworkLagEffect
from chaos_librarian.errors import ChaosLibrarianError


def network_lag_str(entry: JournalEntry, key: str, *, error_type: type[ChaosLibrarianError]) -> str:
    value = entry.state_delta.get(key)
    if not isinstance(value, str):
        raise error_type(f"{entry.event_id}: missing network-lag {key}")
    return value


def network_lag_optional_str(
    entry: JournalEntry, key: str, *, error_type: type[ChaosLibrarianError]
) -> str | None:
    value = entry.state_delta.get(key)
    if value is None or isinstance(value, str):
        return value
    raise error_type(f"{entry.event_id}: invalid network-lag {key}")


def network_lag_int(entry: JournalEntry, key: str, *, error_type: type[ChaosLibrarianError]) -> int:
    value = entry.state_delta.get(key)
    if isinstance(value, int):
        return value
    raise error_type(f"{entry.event_id}: missing network-lag {key}")


def network_lag_effect(
    entry: JournalEntry, *, error_type: type[ChaosLibrarianError]
) -> NetworkLagEffect:
    return NetworkLagEffect(network_lag_str(entry, "effect", error_type=error_type))
