"""Per-rule tests for ``rule_target_unknown`` (E_TARGET_UNKNOWN) and
``rule_root_unknown`` (E_ROOT_UNKNOWN)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule4TargetUnknown:
    """Every timeline target: must resolve to a real asset id.

    WHY: an unresolved target would crash the materializer at runtime;
    catching it at validate avoids polluting the journal with a half-
    applied event.
    """

    def test_unknown_target(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "ghost"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_TARGET_UNKNOWN and "ghost" in i.message for i in collector.issues
        )

    def test_known_target_passes(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_TARGET_UNKNOWN for i in collector.issues)

    def test_slow_copy_commit_has_no_target_so_no_check(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "1s",
                },
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_TARGET_UNKNOWN for i in collector.issues)


class TestRule12RootUnknown:
    """move_between_roots root ids and archive_root must resolve.

    WHY: an unknown ``from_root_id`` / ``to_root_id`` would leave the
    materializer with no source or destination directory; an unknown
    ``archive_root`` would point the archive handler at a path that
    isn't under the library. Catching at validate avoids surfacing
    these as runtime errors mid-scenario.
    """

    def test_move_between_roots_unknown_from_root_id_emits_e_root_unknown(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            library={"roots": [{"id": "movies-hd", "path": "library/movies-hd"}]},
            timeline=[
                {
                    "id": "ev_mbr",
                    "at": "0ns",
                    "action": "move_between_roots",
                    "target": "a",
                    "from_root_id": "missing-root",
                    "to_root_id": "movies-hd",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        root_issues = [i for i in collector.issues if i.code == codes.E_ROOT_UNKNOWN]
        assert [i.code for i in root_issues] == [codes.E_ROOT_UNKNOWN]
        assert "missing-root" in root_issues[0].message
        assert root_issues[0].path == "$.timeline[0].from_root_id"

    def test_move_between_roots_unknown_to_root_id_emits_e_root_unknown(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            library={"roots": [{"id": "movies-hd", "path": "library/movies-hd"}]},
            timeline=[
                {
                    "id": "ev_mbr",
                    "at": "0ns",
                    "action": "move_between_roots",
                    "target": "a",
                    "from_root_id": "movies-hd",
                    "to_root_id": "missing-root",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        root_issues = [i for i in collector.issues if i.code == codes.E_ROOT_UNKNOWN]
        assert [i.code for i in root_issues] == [codes.E_ROOT_UNKNOWN]
        assert "missing-root" in root_issues[0].message
        assert root_issues[0].path == "$.timeline[0].to_root_id"

    def test_archive_root_unknown_emits_e_root_unknown(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            library={
                "roots": [{"id": "movies-hd", "path": "library/movies-hd"}],
                "archive_root": "ghost-root",
            },
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        root_issues = [i for i in collector.issues if i.code == codes.E_ROOT_UNKNOWN]
        assert [i.code for i in root_issues] == [codes.E_ROOT_UNKNOWN]
        assert root_issues[0].path == "$.library.archive_root"

    def test_archive_root_sentinel_value_valid(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            library={
                "roots": [{"id": "movies-hd", "path": "library/movies-hd"}],
                "archive_root": "archive",
            },
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_ROOT_UNKNOWN for i in collector.issues)

    def test_archive_root_none_valid(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            library={
                "roots": [{"id": "movies-hd", "path": "library/movies-hd"}],
                "archive_root": None,
            },
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_ROOT_UNKNOWN for i in collector.issues)

    def test_archive_root_referencing_declared_root_valid(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            library={
                "roots": [
                    {"id": "movies-hd", "path": "library/movies-hd"},
                    {"id": "cold-storage", "path": "library/cold-storage"},
                ],
                "archive_root": "cold-storage",
            },
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_ROOT_UNKNOWN for i in collector.issues)
