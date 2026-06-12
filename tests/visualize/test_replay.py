"""Replay + snapshot tests for the visualizer."""

from __future__ import annotations

import pytest

from chaos_librarian.visualize.errors import JournalCorruptLineError
from chaos_librarian.visualize.replay import ParsedJournal, parse_journal_text

_GOOD = (
    '{"schema_version":1,"event_id":"e1","scenario_id":"s","run_id":'
    '"00000000-0000-0000-0000-000000000000","logical_time_ns":1,"action":'
    '"add_file","phase":"atomic"}'
)


def test_all_lines_parse_no_torn_flag() -> None:
    result = parse_journal_text(_GOOD + "\n" + _GOOD + "\n")
    assert isinstance(result, ParsedJournal)
    assert len(result.entries) == 2
    assert result.ended_mid_write is False


def test_torn_final_line_is_dropped_with_flag() -> None:
    result = parse_journal_text(_GOOD + "\n" + '{"schema_version":1,"event')
    assert len(result.entries) == 1
    assert result.ended_mid_write is True


def test_single_torn_line_yields_empty_prefix() -> None:
    # A run that crashed after its very first (incomplete) write.
    result = parse_journal_text('{"schema_version":1,"event')
    assert result.entries == []
    assert result.ended_mid_write is True


def test_corrupt_nonfinal_line_is_hard_error() -> None:
    with pytest.raises(JournalCorruptLineError) as exc:
        parse_journal_text('{"broken":true}\n' + _GOOD + "\n")
    assert exc.value.line == 1


def test_empty_text_is_empty_prefix() -> None:
    result = parse_journal_text("")
    assert result.entries == []
    assert result.ended_mid_write is False
