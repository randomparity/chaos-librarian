"""Adapt phase-B dispatcher state into materialization report action groups."""

from __future__ import annotations

from collections.abc import Sequence

from chaos_librarian.contract.materialization import NetworkFsChaosAction
from chaos_librarian.materializer.persistence._context import ReportActions
from chaos_librarian.materializer.phase_b.dispatch import PhaseBState

__all__ = ["report_actions_from_phase_b"]


def report_actions_from_phase_b(
    state: PhaseBState,
    *,
    network_fs_chaos_actions: Sequence[NetworkFsChaosAction] = (),
) -> ReportActions:
    """Return the report action groups captured by a phase-B dispatch state."""
    return ReportActions(
        filesystem=state.filesystem_actions,
        media=state.media_actions,
        corruption=state.corruption_actions,
        oracle_hash=state.oracle_hash_actions,
        network_lag=state.network_lag_actions,
        network_fs_chaos=list(network_fs_chaos_actions),
    )
