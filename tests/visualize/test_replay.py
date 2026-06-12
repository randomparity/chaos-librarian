"""Replay + snapshot tests for the visualizer."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    ScenarioRevalidationError,
)
from chaos_librarian.visualize.replay import (
    ParsedJournal,
    ReplayResult,
    parse_journal_text,
    replay_with_snapshots,
)

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


_FIXTURE = "tests/fixtures/scenarios/active-library-churn.yaml"


def _plan_run_dir(tmp_path: Path, *, steps: int | None = None) -> Path:
    out = tmp_path / "run"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["uv", "run", "chaos-librarian", "plan", _FIXTURE, "--out", str(out)]
    if steps is not None:
        cmd += ["--steps", str(steps)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def test_snapshot_count_is_event_count_plus_one(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    result = replay_with_snapshots(run_dir)
    assert isinstance(result, ReplayResult)
    assert len(result.snapshots) == len(result.events) + 1
    assert result.live_count == len(result.events)
    assert result.ended_mid_write is False


def test_initial_snapshot_is_seeded_state(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    result = replay_with_snapshots(run_dir)
    assert "locations" in result.snapshots[0]


def test_prefix_run_marks_planned_tail(tmp_path: Path) -> None:
    full = replay_with_snapshots(_plan_run_dir(tmp_path / "a"))
    partial = replay_with_snapshots(_plan_run_dir(tmp_path / "b", steps=1))
    assert partial.total_events == full.total_events
    assert partial.live_count < full.total_events


def test_divergent_journal_is_hard_error(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    journal = run_dir / "journal.jsonl"
    lines = journal.read_text().splitlines()
    # Rewrite the first entry's event_id via a JSON round-trip so the line
    # stays valid JSON but diverges from the replayed event_id.
    first = json.loads(lines[0])
    first["event_id"] = "TAMPERED"
    lines[0] = json.dumps(first)
    journal.write_text("\n".join(lines) + "\n")
    with pytest.raises(JournalDivergenceError) as exc:
        replay_with_snapshots(run_dir)
    assert exc.value.disk_event_id == "TAMPERED"
    assert exc.value.position == 0


def test_journal_longer_than_timeline_is_divergence(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    journal = run_dir / "journal.jsonl"
    lines = journal.read_text().splitlines()
    # Append a synthetic extra entry past the resolved timeline's end (valid
    # JSON, fresh event_id) to trigger the len(disk) > len(replayed) branch.
    extra = json.loads(lines[-1])
    extra["event_id"] = "EXTRA_PAST_END"
    lines.append(json.dumps(extra))
    journal.write_text("\n".join(lines) + "\n")
    with pytest.raises(JournalDivergenceError) as exc:
        replay_with_snapshots(run_dir)
    assert exc.value.position == len(lines) - 1
    assert exc.value.disk_event_id == "EXTRA_PAST_END"
    assert "end of timeline" in exc.value.replay_event_id


def test_unrevalidatable_scenario_is_clean_error(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    bundle_path = run_dir / "replay.json"
    bundle = json.loads(bundle_path.read_text())
    # Inject an unknown top-level key into the embedded scenario YAML so it
    # fails re-validation (every contract model is extra="forbid"). The .ok
    # guard fires before any run_id/digest check, so this is a clean error,
    # not a bare pydantic ValidationError.
    bundle["scenario"] = bundle["scenario"] + "\nnot_a_real_scenario_key: true\n"
    bundle_path.write_text(json.dumps(bundle))
    with pytest.raises(ScenarioRevalidationError) as exc:
        replay_with_snapshots(run_dir)
    assert exc.value.codes  # non-empty list of error codes
