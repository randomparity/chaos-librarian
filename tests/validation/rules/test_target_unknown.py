"""Per-rule tests for ``rule_target_unknown`` (E_TARGET_UNKNOWN)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
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
