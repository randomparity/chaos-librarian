"""Per-rule tests for ``rule_path_containment`` (E_PATH_CONTAINMENT, timeline paths)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule6PathContainment:
    """Every scenario path must pass the containment helper.

    WHY: a path that resolves outside the library root is a filesystem-
    safety violation; the runtime (plan/materialize) would refuse to
    write there. Catching at validate prevents partial runs.
    """

    def test_absolute_root_path_rejected(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        library = as_dict(raw["library"])
        roots = as_list(library["roots"])
        first_root = as_dict(roots[0])
        first_root["path"] = "/etc/passwd"
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_dotdot_escape_in_to(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "../../etc/passwd",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_temp_path_checked(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "movies/x.mkv",
                    "temp_path": "/tmp/x.part",  # absolute — rejected
                    "duration": "1s",
                },
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        # at least one E_PATH_CONTAINMENT against the temp_path
        assert any(
            i.code == codes.E_PATH_CONTAINMENT and "temp_path" in (i.path or "")
            for i in collector.issues
        )

    def test_valid_relative_paths_no_issue(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "movies-hd/Foo.mkv",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)
