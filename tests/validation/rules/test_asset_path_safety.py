"""Per-rule tests for rendered asset path safety."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRuleAssetPathSafety:
    """Rendered asset and declared sidecar paths must be safe.

    WHY: ``build_initial_state`` uses the shared renderer. Validation must
    reject the same display-derived path failures before the engine can
    crash while building initial state.
    """

    def test_asset_id_with_traversal_is_not_treated_as_path_component(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        movie = as_dict(as_list(raw["movies"])[0])
        variant = as_dict(as_list(movie["variants"])[0])
        assets = as_list(as_dict(variant["bundle"])["assets"])
        as_dict(assets[0])["id"] = "../../escape"
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_asset_container_with_separator_flagged(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        movie = as_dict(as_list(raw["movies"])[0])
        variant = as_dict(as_list(movie["variants"])[0])
        assets = as_list(as_dict(variant["bundle"])["assets"])
        as_dict(assets[0])["container"] = "../foo"
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_PATH_CONTAINMENT]
        assert any("asset_container" in i.message for i in issues)

    def test_safe_asset_passes(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario()
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)
