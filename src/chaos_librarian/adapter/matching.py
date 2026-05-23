"""Deterministic asset matching for adapter comparisons."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from chaos_librarian.adapter.index import ObservedIndex, OracleIndex
from chaos_librarian.contract.divergence import (
    DivergenceCode,
    DivergenceFinding,
    DivergenceSeverity,
    MatchEvidence,
    MatchEvidenceKind,
)


@dataclass(frozen=True)
class AssetMatch:
    oracle_asset_id: str
    observed_ref: str
    evidence: tuple[MatchEvidence, ...]


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[AssetMatch, ...]
    findings: tuple[DivergenceFinding, ...]
    unmatched_oracle_asset_ids: tuple[str, ...]
    unmatched_observed_refs: tuple[str, ...]
    ambiguous_oracle_asset_ids: tuple[str, ...]
    ambiguous_observed_refs: tuple[str, ...]


def match_assets(oracle_index: OracleIndex, observed_index: ObservedIndex) -> MatchResult:
    """Match oracle assets to observed assets by ranked deterministic evidence."""
    state = _MatchState()
    _apply_level(
        state,
        oracle_index.current_path_to_asset_ids,
        observed_index.current_path_to_refs,
        evidence_kind="current_path",
    )
    _apply_level(
        state,
        oracle_index.historical_path_to_asset_ids,
        observed_index.historical_path_to_refs,
        evidence_kind="historical_path",
    )
    _apply_level(
        state,
        oracle_index.hash_to_asset_ids,
        observed_index.hash_to_refs,
        evidence_kind="content_hash",
    )
    _apply_level(
        state,
        oracle_index.topology_key_to_asset_ids,
        observed_index.topology_key_to_refs,
        evidence_kind="topology",
    )
    _add_unmatched_findings(state, oracle_index, observed_index)
    return state.result(oracle_index, observed_index)


@dataclass
class _MatchState:
    matches: list[AssetMatch] = field(default_factory=list)
    findings: list[DivergenceFinding] = field(default_factory=list)
    matched_oracle: set[str] = field(default_factory=set)
    matched_observed: set[str] = field(default_factory=set)
    ambiguous_oracle: set[str] = field(default_factory=set)
    ambiguous_observed: set[str] = field(default_factory=set)

    def result(self, oracle_index: OracleIndex, observed_index: ObservedIndex) -> MatchResult:
        unmatched_oracle = _sorted_unmatched(
            oracle_index.assets,
            matched=self.matched_oracle,
            ambiguous=self.ambiguous_oracle,
        )
        unmatched_observed = _sorted_unmatched(
            observed_index.assets,
            matched=self.matched_observed,
            ambiguous=self.ambiguous_observed,
        )
        return MatchResult(
            matches=tuple(self.matches),
            findings=tuple(self.findings),
            unmatched_oracle_asset_ids=unmatched_oracle,
            unmatched_observed_refs=unmatched_observed,
            ambiguous_oracle_asset_ids=tuple(sorted(self.ambiguous_oracle)),
            ambiguous_observed_refs=tuple(sorted(self.ambiguous_observed)),
        )


def _apply_level(
    state: _MatchState,
    oracle_lookup: Mapping[str, tuple[str, ...]],
    observed_lookup: Mapping[str, tuple[str, ...]],
    *,
    evidence_kind: MatchEvidenceKind,
) -> None:
    for key in sorted(set(oracle_lookup) & set(observed_lookup)):
        oracle_ids = _eligible(oracle_lookup[key], state.matched_oracle, state.ambiguous_oracle)
        observed_refs = _eligible(
            observed_lookup[key],
            state.matched_observed,
            state.ambiguous_observed,
        )
        if not oracle_ids or not observed_refs:
            continue
        if len(oracle_ids) == 1 and len(observed_refs) == 1:
            _record_match(state, oracle_ids[0], observed_refs[0], evidence_kind, key)
            continue
        _record_ambiguity(state, oracle_ids, observed_refs, evidence_kind, key)


def _eligible(values: tuple[str, ...], matched: set[str], ambiguous: set[str]) -> tuple[str, ...]:
    return tuple(value for value in values if value not in matched and value not in ambiguous)


def _record_match(
    state: _MatchState,
    oracle_asset_id: str,
    observed_ref: str,
    evidence_kind: MatchEvidenceKind,
    value: str,
) -> None:
    state.matches.append(
        AssetMatch(
            oracle_asset_id=oracle_asset_id,
            observed_ref=observed_ref,
            evidence=(
                MatchEvidence(
                    kind=evidence_kind,
                    value=value,
                    oracle_asset_id=oracle_asset_id,
                    observed_ref=observed_ref,
                ),
            ),
        )
    )
    state.matched_oracle.add(oracle_asset_id)
    state.matched_observed.add(observed_ref)


def _record_ambiguity(
    state: _MatchState,
    oracle_ids: tuple[str, ...],
    observed_refs: tuple[str, ...],
    evidence_kind: MatchEvidenceKind,
    value: str,
) -> None:
    state.ambiguous_oracle.update(oracle_ids)
    state.ambiguous_observed.update(observed_refs)
    state.findings.append(
        DivergenceFinding(
            code=DivergenceCode.MATCH_AMBIGUOUS,
            severity=DivergenceSeverity.ERROR,
            message=f"Ambiguous {evidence_kind} match for {value}.",
            expected={"oracle_asset_ids": list(oracle_ids)},
            observed={"observed_refs": list(observed_refs)},
            evidence=[MatchEvidence(kind=evidence_kind, value=value)],
        )
    )


def _add_unmatched_findings(
    state: _MatchState, oracle_index: OracleIndex, observed_index: ObservedIndex
) -> None:
    for asset_id in _sorted_unmatched(
        oracle_index.assets,
        matched=state.matched_oracle,
        ambiguous=state.ambiguous_oracle,
    ):
        state.findings.append(
            DivergenceFinding(
                code=DivergenceCode.ASSET_MISSING,
                severity=DivergenceSeverity.ERROR,
                message=f"Oracle asset {asset_id} has no observed match.",
                oracle_asset_id=asset_id,
            )
        )
    for observed_ref in _sorted_unmatched(
        observed_index.assets,
        matched=state.matched_observed,
        ambiguous=state.ambiguous_observed,
    ):
        state.findings.append(
            DivergenceFinding(
                code=DivergenceCode.ASSET_UNEXPECTED,
                severity=DivergenceSeverity.ERROR,
                message=f"Observed asset {observed_ref} has no oracle match.",
                observed_ref=observed_ref,
            )
        )


def _sorted_unmatched(
    values: Mapping[str, object], *, matched: set[str], ambiguous: set[str]
) -> tuple[str, ...]:
    return tuple(
        sorted(value for value in values if value not in matched and value not in ambiguous)
    )
