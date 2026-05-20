"""Shared types, raw-data narrowing helpers, and cross-rule walkers for
``validation/rules/``.

Every rule module in this subpackage imports the ``Rule`` callable type
and the shape-narrowing helpers from here. ``IssueCollector`` and
``LineIndex`` are kept behind ``TYPE_CHECKING`` because importing them
at runtime would re-introduce the ``pipeline → semantic → rules →
pipeline`` import cycle that the package layout is designed to avoid.

The ``iter_*`` walkers and ``NS_*`` namespace constants live here so that
rule modules depend on each other only through ``semantic.py``'s
``_RULES`` registry, never through direct imports of cross-cutting
walkers. See issue #27.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from chaos_librarian.clock import DurationParseError, parse_duration
from chaos_librarian.contract.validation import ValidationSeverity

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = [
    "NS_ASSET_ID",
    "NS_BUNDLE_ID",
    "NS_VARIANT_ID",
    "Reporter",
    "Rule",
    "_Loc",
    "_RawMapping",
    "_as_list",
    "_as_mapping",
    "_iter_timeline_events",
    "_list_at_path",
    "iter_asset_ids",
    "iter_assets_with_loc",
    "iter_global_namespaces",
    "try_parse_duration",
]


_Loc = tuple[str | int, ...]
_RawMapping = Mapping[str, object]
Rule = Callable[[_RawMapping, "LineIndex", "IssueCollector"], None]


@dataclass(frozen=True, slots=True)
class Reporter:
    """Binds ``collector`` + ``line_index`` once per rule invocation.

    Replaces 5-kwarg ``collector.add(code=..., severity=...,
    message=..., loc=..., line_index=line_index)`` sites with 3-kwarg
    ``reporter.error(code=..., message=..., loc=...)``. Internal
    rule helpers thread one ``reporter`` arg instead of carrying
    ``collector`` and ``line_index`` separately.
    """

    collector: IssueCollector
    line_index: LineIndex

    def error(self, *, code: str, message: str, loc: _Loc) -> None:
        self.collector.add(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            loc=loc,
            line_index=self.line_index,
        )

    def warning(self, *, code: str, message: str, loc: _Loc) -> None:
        self.collector.add(
            code=code,
            severity=ValidationSeverity.WARNING,
            message=message,
            loc=loc,
            line_index=self.line_index,
        )


# Typo-safe namespace keys for ``iter_global_namespaces`` callers — string
# literals would silently break the namespace filter / per-namespace dicts.
NS_VARIANT_ID: Final = "variant_id"
NS_BUNDLE_ID: Final = "bundle_id"
NS_ASSET_ID: Final = "asset_id"


def _as_mapping(node: object) -> _RawMapping | None:
    """Narrow an ``object`` to ``Mapping[str, object]`` for safe ``.get`` calls.

    Returns None when ``node`` is non-mapping so the rule can skip the malformed
    sub-tree (Pydantic's shape pass owns the E_FIELD_TYPE report). ``cast`` is
    needed because ``isinstance`` against a generic alias is erased at runtime.
    """
    if isinstance(node, Mapping):
        return cast("_RawMapping", node)
    return None


def _as_list(node: object) -> list[object] | None:
    """Narrow an ``object`` to ``list[object]``; mirror of ``_as_mapping``."""
    if isinstance(node, list):
        return cast("list[object]", node)
    return None


def _list_at_path(raw: _RawMapping, path_parts: tuple[str, ...]) -> list[object] | None:
    """Walk ``path_parts`` from ``raw`` and return the list at the end, or None."""
    node: object = raw
    for part in path_parts:
        parent = _as_mapping(node)
        if parent is None:
            return None
        node = parent.get(part)
    return _as_list(node)


def _iter_timeline_events(raw: _RawMapping) -> Iterator[tuple[int, _RawMapping]]:
    """Yield ``(idx, event)`` for each well-shaped event under ``raw["timeline"]``.

    Centralizes the iterate-and-narrow preamble every timeline-walking rule
    needs. Malformed events (non-mapping) are skipped silently — the shape
    pass already reported them.
    """
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        yield idx, event


def try_parse_duration(raw_str: str) -> int | None:
    """Parse a duration string; return None instead of raising.

    Rules that re-parse a duration string for arithmetic (5b: slow-copy
    timing, 7: timeline order) need to skip pairs where the input is
    malformed — Rule 3 has already flagged those with E_DURATION_SYNTAX,
    and re-reporting them as order/timing failures would be noise.
    """
    try:
        return parse_duration(raw_str)
    except DurationParseError:
        return None


def iter_global_namespaces(
    raw: _RawMapping,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``(namespace, id_value, loc)`` for every variant/bundle/asset id.

    Walks ``works[*].variants[*].bundle.assets[*]`` and skips any sub-tree
    whose shape Pydantic would have rejected; shape errors are surfaced by
    the shape pass, not here.
    """
    works = _as_list(raw.get("works"))
    if works is None:
        return
    for w_idx, work_obj in enumerate(works):
        work = _as_mapping(work_obj)
        if work is None:
            continue
        variants = _as_list(work.get("variants"))
        if variants is None:
            continue
        for v_idx, variant in enumerate(variants):
            yield from _iter_variant(variant, w_idx=w_idx, v_idx=v_idx)


def iter_asset_ids(raw: _RawMapping) -> Iterator[str]:
    """Yield every ``asset_id`` value defined in the scenario.

    Implemented as a filter over ``iter_global_namespaces`` rather than a
    fresh walker so the shape-skipping logic stays in one place; Rule 1
    needs the locs (and the variant/bundle namespaces), Rules 4 and 8
    only need the asset-id values.
    """
    for namespace, value, _ in iter_global_namespaces(raw):
        if namespace == NS_ASSET_ID:
            yield value


def iter_assets_with_loc(
    raw: _RawMapping,
) -> Iterator[tuple[_RawMapping, _Loc]]:
    """Yield ``(asset_mapping, loc)`` for every well-shaped asset.

    Reuses the same walk shape as ``iter_global_namespaces`` but yields
    the full asset sub-mapping so rules can inspect any field on it.
    """
    works = _as_list(raw.get("works"))
    if works is None:
        return
    for w_idx, work_obj in enumerate(works):
        work = _as_mapping(work_obj)
        if work is None:
            continue
        variants = _as_list(work.get("variants"))
        if variants is None:
            continue
        for v_idx, variant_obj in enumerate(variants):
            variant = _as_mapping(variant_obj)
            if variant is None:
                continue
            bundle = _as_mapping(variant.get("bundle"))
            if bundle is None:
                continue
            assets = _as_list(bundle.get("assets"))
            if assets is None:
                continue
            for a_idx, asset_obj in enumerate(assets):
                asset = _as_mapping(asset_obj)
                if asset is None:
                    continue
                loc: _Loc = (
                    "works",
                    w_idx,
                    "variants",
                    v_idx,
                    "bundle",
                    "assets",
                    a_idx,
                )
                yield asset, loc


def _iter_variant(
    variant_obj: object,
    *,
    w_idx: int,
    v_idx: int,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ids for one variant and the bundle/assets nested below it."""
    variant = _as_mapping(variant_obj)
    if variant is None:
        return
    v_id = variant.get("id")
    if isinstance(v_id, str):
        yield NS_VARIANT_ID, v_id, ("works", w_idx, "variants", v_idx, "id")
    bundle = _as_mapping(variant.get("bundle"))
    if bundle is None:
        return
    b_id = bundle.get("id")
    bundle_path: _Loc = ("works", w_idx, "variants", v_idx, "bundle")
    if isinstance(b_id, str):
        yield NS_BUNDLE_ID, b_id, (*bundle_path, "id")
    yield from _iter_bundle_assets(bundle.get("assets"), bundle_path=bundle_path)


def _iter_bundle_assets(
    assets_obj: object,
    *,
    bundle_path: _Loc,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``asset_id`` triples for each well-shaped asset under a bundle."""
    assets = _as_list(assets_obj)
    if assets is None:
        return
    for a_idx, asset_obj in enumerate(assets):
        asset = _as_mapping(asset_obj)
        if asset is None:
            continue
        a_id = asset.get("id")
        if isinstance(a_id, str):
            yield NS_ASSET_ID, a_id, (*bundle_path, "assets", a_idx, "id")
