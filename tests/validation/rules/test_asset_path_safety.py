"""Per-rule tests for ``rule_asset_id_container_safe`` (E_PATH_CONTAINMENT on asset fields)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRuleAssetPathSafety:
    """Asset id and container must be safe single path components.

    WHY: ``build_initial_state`` synthesizes the initial location path as
    ``f"{root.path}/{asset.id}.{asset.container}"``. A traversal sequence
    in either field would produce an initial manifest path outside the
    library root before the engine has a chance to resolve anything. The
    rule lives at validate time so the engine can keep treating its inputs
    as trusted. Reuses ``E_PATH_CONTAINMENT`` — same containment guarantee,
    same code so the public taxonomy stays stable. Closes Codex
    adversarial-review finding 3.
    """

    def test_asset_id_with_traversal_flagged(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        assets = as_list(
            as_dict(as_list(as_list(raw["works"])[0]["variants"])[0]["bundle"])["assets"]
        )
        as_dict(assets[0])["id"] = "../../escape"
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_PATH_CONTAINMENT]
        assert any("asset.id" in i.message and "../../escape" in i.message for i in issues)

    def test_asset_container_with_separator_flagged(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        assets = as_list(
            as_dict(as_list(as_list(raw["works"])[0]["variants"])[0]["bundle"])["assets"]
        )
        as_dict(assets[0])["container"] = "../foo"
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_PATH_CONTAINMENT]
        assert any("asset.container" in i.message and "../foo" in i.message for i in issues)

    def test_safe_asset_passes(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario()
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        # The minimal scenario uses id="a", container="mkv" — both safe.
        # If a future minimal-scenario change introduces an unsafe value
        # here, this assertion catches it.
        assert not any(
            i.code == codes.E_PATH_CONTAINMENT and "asset." in i.message for i in collector.issues
        )
