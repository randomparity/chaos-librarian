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

    def test_unsafe_variant_label_reports_variant_label_path(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        movie = as_dict(as_list(raw["movies"])[0])
        variant = as_dict(as_list(movie["variants"])[0])
        variant["label"] = "."
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_PATH_CONTAINMENT]
        assert any(i.path == "$.movies[0].variants[0].label" for i in issues)

    def test_unsafe_multi_asset_role_reports_asset_role_path(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        movie = as_dict(as_list(raw["movies"])[0])
        variant = as_dict(as_list(movie["variants"])[0])
        bundle = as_dict(variant["bundle"])
        assets = as_list(bundle["assets"])
        second_asset = dict(assets[0])
        second_asset["id"] = "asset_two"
        second_asset["role"] = "."
        assets.append(second_asset)
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_PATH_CONTAINMENT]
        assert any(i.path == "$.movies[0].variants[0].bundle.assets[1].role" for i in issues)

    def test_safe_asset_passes(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario()
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)


class TestRuleRemuxContainerSafe:
    """remux_container.to_container must obey the initial-container constraint.

    WHY: the projection state machine swaps the path extension to the raw
    ``to_container`` with no validation. A target carrying path syntax escapes
    containment for every later projection consumer, exactly like an unsafe
    initial ``container`` would. The same constraint must guard both.
    """

    def _remux(self, to_container: object) -> dict[str, object]:
        return {
            "id": "e1",
            "action": "remux_container",
            "target": "a",
            "to_container": to_container,
        }

    def test_traversal_target_flagged(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(timeline=[self._remux("mp4/../../etc")])
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_PATH_CONTAINMENT]
        assert any(i.path == "$.timeline[0].to_container" for i in issues)

    def test_separator_target_flagged(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(timeline=[self._remux("foo/bar")])
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_PATH_CONTAINMENT and i.path == "$.timeline[0].to_container"
            for i in collector.issues
        )

    def test_backslash_target_flagged(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(timeline=[self._remux("foo\\bar")])
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_embedded_dot_target_flagged(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(timeline=[self._remux("tar.gz")])
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_safe_target_passes(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(timeline=[self._remux("mp4")])
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_non_string_target_ignored(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(timeline=[self._remux(123)])
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)
