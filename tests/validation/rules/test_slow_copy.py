"""Per-rule tests for ``rule_slow_copy_unpaired`` (5a) and ``rule_slow_copy_timing`` (5b)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule5aSlowCopyUnpaired:
    """Structural pairing for slow_copy_start / slow_copy_commit.

    WHY: an orphan commit applies nothing (the temp file does not exist);
    an orphan start leaves a permanent temp file in the library.
    """

    def test_commit_without_start(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "c1", "at": "1s", "action": "slow_copy_commit", "for": "ghost"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_start_without_commit(self, minimal_scenario, empty_index) -> None:
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
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_two_commits_for_one_start(self, minimal_scenario, empty_index) -> None:
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
                {"id": "c2", "at": "3s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_correctly_paired_no_issue(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "4s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)


class TestRule5bSlowCopyTiming:
    """For each matched pair, commit.at must equal start.at + start.duration.

    WHY: the design spec says the temp file is "grown over the declared
    duration: between the two events." Any drift would mean either an
    idle gap (commit too late) or premature commit (impossible). Closes
    Codex review finding #2.
    """

    def test_commit_too_early_is_error(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "3s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_commit_too_late_is_error(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "5s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_exact_match_no_issue(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "4s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_skipped_when_durations_unparseable(self, minimal_scenario, empty_index) -> None:
        """Rule 3 already flags; Rule 5b must not double-report."""
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "bogus",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "4s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)
