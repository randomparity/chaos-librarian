"""Per-rule tests for ``rule_path_duplicate`` (E_PATH_DUPLICATE)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule2PathDuplicate:
    """Two library roots sharing the same path emit a WARNING, not an ERROR.

    WHY: duplicate paths under distinct IDs are well-defined (alias) but
    almost always a typo; flagging without flipping ok lets validate
    still pass on legitimate aliases.
    """

    def test_warning_severity_no_exit_flip(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        library = as_dict(raw["library"])
        roots = as_list(library["roots"])
        roots.append({"id": "r2", "path": "r"})  # same path
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        warnings = [i for i in collector.issues if i.code == codes.E_PATH_DUPLICATE]
        assert len(warnings) == 1
        assert warnings[0].severity.value == "warning"

    def test_distinct_paths_no_warning(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        raw = minimal_scenario()
        library = as_dict(raw["library"])
        roots = as_list(library["roots"])
        roots.append({"id": "r2", "path": "r2"})
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_PATH_DUPLICATE for i in collector.issues)
