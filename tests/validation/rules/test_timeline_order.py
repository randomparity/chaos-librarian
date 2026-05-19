"""Per-rule tests for ``rule_timeline_order`` (E_TIMELINE_ORDER)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule7TimelineOrder:
    """Timeline at: values must be non-decreasing.

    WHY: the design spec says events with the same at: apply in declared
    order. A scenario that goes backwards in time would either crash the
    materializer or produce a journal whose logical_time_ns is non-
    monotonic — both make replay impossible.
    """

    def test_out_of_order_flagged(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "5s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_TIMELINE_ORDER for i in collector.issues)

    def test_ties_allowed(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_TIMELINE_ORDER for i in collector.issues)

    def test_unparseable_skipped(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "bogus", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        # Rule 3 fires; Rule 7 must not double-report.
        assert not any(i.code == codes.E_TIMELINE_ORDER for i in collector.issues)
