"""Identity-history comparison for matched assets."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from chaos_librarian.adapter.index import ObservedAssetView, ObservedIndex, OracleIndex
from chaos_librarian.adapter.matching import AssetMatch, MatchResult
from chaos_librarian.contract.divergence import (
    DivergenceCode,
    DivergenceFinding,
    DivergenceSeverity,
)
from chaos_librarian.contract.observed_state import (
    ObservedAction,
    ObservedEvent,
    ObservedPathHistoryEntry,
)
from chaos_librarian.contract.reports import PathHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName

IDENTITY_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
        TimelineActionName.ADD_FILE,
        TimelineActionName.SLOW_COPY_START,
        TimelineActionName.SLOW_COPY_COMMIT,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
    }
)

_Source = Literal["path_history", "global"]


@dataclass(frozen=True)
class OracleLifecycle:
    action: TimelineActionName
    event_ids: tuple[str, ...]
    from_path: str | None
    to_path: str | None
    temp_path: str | None

    @property
    def signature(self) -> tuple[str, str | None, str | None, str | None]:
        return self.action.value, self.from_path, self.to_path, self.temp_path


@dataclass(frozen=True)
class ObservedLifecycleEvidence:
    action: ObservedAction
    observed_ref_before: str
    observed_ref_after: str
    from_path: str | None
    to_path: str | None
    temp_path: str | None
    observed_event_ref: str | None
    source: _Source

    @property
    def signature(self) -> tuple[str, str | None, str | None, str | None]:
        return self.action.value, self.from_path, self.to_path, self.temp_path


def compare_identity_history(
    match_result: MatchResult,
    oracle_index: OracleIndex,
    observed_index: ObservedIndex,
) -> tuple[DivergenceFinding, ...]:
    """Compare identity lifecycle evidence for matched assets."""
    findings: list[DivergenceFinding] = []
    for match in match_result.matches:
        oracle_asset = oracle_index.assets[match.oracle_asset_id]
        observed_asset = observed_index.assets[match.observed_ref]
        expected = _oracle_lifecycles(oracle_asset.path_history)
        observed = _observed_lifecycles(observed_asset, observed_index.events)
        findings.extend(_compare_lifecycles(match, expected, observed))
    return tuple(findings)


def _oracle_lifecycles(entries: tuple[PathHistoryEntry, ...]) -> tuple[OracleLifecycle, ...]:
    ordered = sorted(entries, key=lambda entry: entry.logical_time_ns)
    used: set[int] = set()
    lifecycles: list[OracleLifecycle] = []
    for index, entry in enumerate(ordered):
        if index in used or entry.action not in IDENTITY_ACTIONS:
            continue
        if entry.action is TimelineActionName.DELETE_FILE:
            partner_index = _next_group_partner(ordered, index, used, _oracle_group_pair)
            if partner_index is not None:
                used.add(partner_index)
                lifecycles.append(_oracle_delete_add(entry, ordered[partner_index]))
                continue
        if entry.action is TimelineActionName.SLOW_COPY_START:
            partner_index = _next_group_partner(ordered, index, used, _oracle_group_pair)
            if partner_index is not None:
                used.add(partner_index)
                lifecycles.append(_oracle_slow_copy(entry, ordered[partner_index]))
                continue
        lifecycles.append(_oracle_single(entry))
    return tuple(lifecycles)


def _next_group_partner[T](
    entries: Sequence[T],
    start_index: int,
    used: set[int],
    is_group_pair: Callable[[T, T], bool],
) -> int | None:
    start = entries[start_index]
    for index in range(start_index + 1, len(entries)):
        if index not in used and is_group_pair(start, entries[index]):
            return index
    return None


def _oracle_group_pair(first: PathHistoryEntry, second: PathHistoryEntry) -> bool:
    if first.action is TimelineActionName.DELETE_FILE:
        return second.action is TimelineActionName.ADD_FILE
    if first.action is TimelineActionName.SLOW_COPY_START:
        return (
            second.action is TimelineActionName.SLOW_COPY_COMMIT and first.to_path == second.to_path
        )
    return False


def _oracle_delete_add(delete: PathHistoryEntry, add: PathHistoryEntry) -> OracleLifecycle:
    return OracleLifecycle(
        action=TimelineActionName.DELETE_FILE,
        event_ids=(delete.event_id, add.event_id),
        from_path=delete.from_path,
        to_path=add.to_path,
        temp_path=None,
    )


def _oracle_slow_copy(start: PathHistoryEntry, commit: PathHistoryEntry) -> OracleLifecycle:
    return OracleLifecycle(
        action=TimelineActionName.SLOW_COPY_START,
        event_ids=(start.event_id, commit.event_id),
        from_path=start.from_path,
        to_path=start.to_path,
        temp_path=start.temp_path,
    )


def _oracle_single(entry: PathHistoryEntry) -> OracleLifecycle:
    return OracleLifecycle(
        action=entry.action,
        event_ids=(entry.event_id,),
        from_path=entry.from_path,
        to_path=entry.to_path,
        temp_path=entry.temp_path,
    )


def _observed_lifecycles(
    asset: ObservedAssetView,
    global_events: tuple[ObservedEvent, ...],
) -> tuple[ObservedLifecycleEvidence, ...]:
    evidence = list(_observed_path_history_lifecycles(asset))
    for event in global_events:
        if _global_event_references(event, asset.observed_ref):
            evidence.append(_observed_global_single(event))
    return tuple(evidence)


def _observed_path_history_lifecycles(
    asset: ObservedAssetView,
) -> tuple[ObservedLifecycleEvidence, ...]:
    entries = list(asset.path_history)
    used: set[int] = set()
    lifecycles: list[ObservedLifecycleEvidence] = []
    for index, entry in enumerate(entries):
        if index in used:
            continue
        if entry.action is ObservedAction.DELETE_FILE:
            partner_index = _next_group_partner(entries, index, used, _observed_group_pair)
            if partner_index is not None:
                used.add(partner_index)
                lifecycles.append(_observed_delete_add(asset, entry, entries[partner_index]))
                continue
        if entry.action is ObservedAction.SLOW_COPY_START:
            partner_index = _next_group_partner(entries, index, used, _observed_group_pair)
            if partner_index is not None:
                used.add(partner_index)
                lifecycles.append(_observed_slow_copy(asset, entry, entries[partner_index]))
                continue
        lifecycles.append(_observed_single(asset, entry))
    return tuple(lifecycles)


def _observed_group_pair(first: ObservedPathHistoryEntry, second: ObservedPathHistoryEntry) -> bool:
    if first.action is ObservedAction.DELETE_FILE:
        return second.action is ObservedAction.ADD_FILE
    if first.action is ObservedAction.SLOW_COPY_START:
        return second.action is ObservedAction.SLOW_COPY_COMMIT and first.to_path == second.to_path
    return False


def _observed_single(
    asset: ObservedAssetView, entry: ObservedPathHistoryEntry
) -> ObservedLifecycleEvidence:
    return ObservedLifecycleEvidence(
        action=entry.action,
        observed_ref_before=asset.observed_ref,
        observed_ref_after=asset.observed_ref,
        from_path=entry.from_path,
        to_path=entry.to_path,
        temp_path=entry.temp_path,
        observed_event_ref=entry.observed_event_ref,
        source="path_history",
    )


def _observed_delete_add(
    asset: ObservedAssetView,
    delete: ObservedPathHistoryEntry,
    add: ObservedPathHistoryEntry,
) -> ObservedLifecycleEvidence:
    return ObservedLifecycleEvidence(
        action=ObservedAction.DELETE_FILE,
        observed_ref_before=asset.observed_ref,
        observed_ref_after=asset.observed_ref,
        from_path=delete.from_path,
        to_path=add.to_path,
        temp_path=None,
        observed_event_ref=delete.observed_event_ref,
        source="path_history",
    )


def _observed_slow_copy(
    asset: ObservedAssetView,
    start: ObservedPathHistoryEntry,
    commit: ObservedPathHistoryEntry,
) -> ObservedLifecycleEvidence:
    return ObservedLifecycleEvidence(
        action=ObservedAction.SLOW_COPY_START,
        observed_ref_before=asset.observed_ref,
        observed_ref_after=asset.observed_ref,
        from_path=start.from_path,
        to_path=start.to_path,
        temp_path=start.temp_path,
        observed_event_ref=start.observed_event_ref or commit.observed_event_ref,
        source="path_history",
    )


def _observed_global_single(event: ObservedEvent) -> ObservedLifecycleEvidence:
    before = event.observed_ref or event.before_observed_ref
    after = event.observed_ref or event.after_observed_ref
    if before is None or after is None:
        raise ValueError("validated global event is missing identity refs")
    return ObservedLifecycleEvidence(
        action=event.action,
        observed_ref_before=before,
        observed_ref_after=after,
        from_path=event.from_path or event.path,
        to_path=event.to_path or event.path,
        temp_path=event.temp_path,
        observed_event_ref=event.observed_event_ref,
        source="global",
    )


def _global_event_references(event: ObservedEvent, observed_ref: str) -> bool:
    return observed_ref in {
        event.observed_ref,
        event.before_observed_ref,
        event.after_observed_ref,
    }


def _compare_lifecycles(
    match: AssetMatch,
    expected: tuple[OracleLifecycle, ...],
    observed: tuple[ObservedLifecycleEvidence, ...],
) -> list[DivergenceFinding]:
    findings: list[DivergenceFinding] = []
    consumed_observed: set[int] = set()
    for lifecycle in expected:
        candidate_indexes = [
            index
            for index, item in enumerate(observed)
            if index not in consumed_observed and item.signature == lifecycle.signature
        ]
        candidates = [observed[index] for index in candidate_indexes]
        if not candidates:
            findings.append(_history_missing(match, lifecycle))
            continue
        finding = _identity_problem(match, lifecycle, candidates)
        if finding is not None:
            findings.append(finding)
        consumed_observed.update(_consumed_candidate_indexes(candidate_indexes, candidates))
    for index, evidence in enumerate(observed):
        if index not in consumed_observed:
            findings.append(_history_unexpected(match, evidence))
    return findings


def _consumed_candidate_indexes(
    candidate_indexes: list[int], candidates: list[ObservedLifecycleEvidence]
) -> set[int]:
    identity_pairs = {(item.observed_ref_before, item.observed_ref_after) for item in candidates}
    if len(identity_pairs) > 1:
        return set(candidate_indexes)
    return {candidate_indexes[0]}


def _identity_problem(
    match: AssetMatch,
    lifecycle: OracleLifecycle,
    candidates: list[ObservedLifecycleEvidence],
) -> DivergenceFinding | None:
    identity_pairs = {(item.observed_ref_before, item.observed_ref_after) for item in candidates}
    if len(identity_pairs) > 1:
        return _history_conflict(match, lifecycle, candidates)
    before, after = next(iter(identity_pairs))
    if before != after:
        return _identity_split(match, lifecycle, candidates[0])
    return None


def _history_missing(match: AssetMatch, lifecycle: OracleLifecycle) -> DivergenceFinding:
    return _history_finding(
        DivergenceCode.HISTORY_MISSING,
        "Observed history is missing expected oracle lifecycle evidence.",
        match,
        lifecycle,
        expected=_lifecycle_payload(lifecycle),
        observed=None,
    )


def _history_conflict(
    match: AssetMatch,
    lifecycle: OracleLifecycle,
    candidates: list[ObservedLifecycleEvidence],
) -> DivergenceFinding:
    return _history_finding(
        DivergenceCode.HISTORY_CONFLICT,
        "Observed history sources disagree for oracle lifecycle evidence.",
        match,
        lifecycle,
        expected=_lifecycle_payload(lifecycle),
        observed={"identity_pairs": [_evidence_identity(item) for item in candidates]},
    )


def _identity_split(
    match: AssetMatch,
    lifecycle: OracleLifecycle,
    evidence: ObservedLifecycleEvidence,
) -> DivergenceFinding:
    return _history_finding(
        DivergenceCode.IDENTITY_SPLIT,
        "Observed identity changes across an oracle lifecycle.",
        match,
        lifecycle,
        expected=_lifecycle_payload(lifecycle),
        observed=_evidence_payload(evidence),
    )


def _history_unexpected(
    match: AssetMatch, evidence: ObservedLifecycleEvidence
) -> DivergenceFinding:
    return DivergenceFinding(
        code=DivergenceCode.HISTORY_UNEXPECTED,
        severity=DivergenceSeverity.ERROR,
        message="Observed history does not map to an oracle lifecycle.",
        oracle_asset_id=match.oracle_asset_id,
        observed_ref=match.observed_ref,
        expected=None,
        observed=_evidence_payload(evidence),
        evidence=list(match.evidence),
    )


def _history_finding(
    code: DivergenceCode,
    message: str,
    match: AssetMatch,
    lifecycle: OracleLifecycle,
    *,
    expected: object | None,
    observed: object | None,
) -> DivergenceFinding:
    return DivergenceFinding(
        code=code,
        severity=DivergenceSeverity.ERROR,
        message=message,
        oracle_asset_id=match.oracle_asset_id,
        oracle_event_id=lifecycle.event_ids[0],
        related_oracle_event_ids=list(lifecycle.event_ids[1:]),
        observed_ref=match.observed_ref,
        expected=expected,
        observed=observed,
        evidence=list(match.evidence),
    )


def _lifecycle_payload(lifecycle: OracleLifecycle) -> dict[str, object | None]:
    return {
        "action": lifecycle.action.value,
        "from_path": lifecycle.from_path,
        "to_path": lifecycle.to_path,
        "temp_path": lifecycle.temp_path,
    }


def _evidence_payload(evidence: ObservedLifecycleEvidence) -> dict[str, object | None]:
    return {
        "action": evidence.action.value,
        "observed_ref_before": evidence.observed_ref_before,
        "observed_ref_after": evidence.observed_ref_after,
        "from_path": evidence.from_path,
        "to_path": evidence.to_path,
        "temp_path": evidence.temp_path,
        "observed_event_ref": evidence.observed_event_ref,
        "source": evidence.source,
    }


def _evidence_identity(evidence: ObservedLifecycleEvidence) -> dict[str, str]:
    return {
        "source": evidence.source,
        "before": evidence.observed_ref_before,
        "after": evidence.observed_ref_after,
    }
