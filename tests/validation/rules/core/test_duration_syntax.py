"""Per-rule tests for ``rule_duration_syntax`` (E_DURATION_SYNTAX)."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule3DurationSyntax:
    """Every duration string in the timeline must parse.

    WHY: bad durations silently coerce to 0 or crash downstream when
    the journal converts them to logical_time_ns; flagging here keeps
    the contract of "validated scenarios always have parseable times."
    """

    def test_bad_at_field(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "not-a-duration", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_DURATION_SYNTAX for i in collector.issues)

    def test_bad_slow_copy_duration(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "bogus",  # parse failure
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_DURATION_SYNTAX and "duration" in (i.path or "")
            for i in collector.issues
        )

    def test_bad_network_lag_duration(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            profiles=["network-fs-lag"],
            timeline=[
                {
                    "id": "rename_001",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "r/a-renamed.mkv",
                },
                {
                    "id": "lag_start_001",
                    "at": "1s",
                    "action": "network_lag_start",
                    "effect": "delayed_rename",
                    "target": "a",
                    "after": "rename_001",
                    "duration": "bogus",  # parse failure
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_DURATION_SYNTAX and "duration" in (i.path or "")
            for i in collector.issues
        )

    def test_bad_touch_mtime_offset(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            profiles=["filesystem-artifacts"],
            timeline=[
                {
                    "id": "mtime_001",
                    "at": "1s",
                    "action": "touch_mtime",
                    "target": "a",
                    "offset": "bogus",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_DURATION_SYNTAX and "offset" in (i.path or "")
            for i in collector.issues
        )

    def test_valid_durations_no_issues(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1m30s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_DURATION_SYNTAX for i in collector.issues)
