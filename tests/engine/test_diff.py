"""Tests for chaos_librarian.engine.diff.compare_fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from chaos_librarian.engine.diff import (
    FixtureDiff,
    FixtureFileDiff,
    compare_fixtures,
    compare_run_replay,
)
from chaos_librarian.engine.plan import run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path, name: str) -> Path:
    """Build a plan-only fixture directory under ``tmp_path/name``."""
    run_input = prepare_run_input(FIXTURE_DIR / "identity-move-rename.yaml")
    report = run_validation(run_input)
    artifacts = run_plan(run_input=run_input, validation_report=report)
    out = tmp_path / name
    write_fixture(out, artifacts, run_input.raw_bytes)
    return out


class TestCompareFixtures:
    """compare_fixtures detects per-file divergences.

    WHY: replay (Task 13) uses this to produce structured exit-6 diffs when
    a regenerated fixture does not match a recorded reference. The tests
    here pin the four divergence shapes the CLI relies on: byte-identical
    (clean), byte-different (with line+preview metadata), missing on one
    side, and extra on one side.
    """

    def test_identical_fixtures_is_clean(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        diff = compare_fixtures(a, b)
        assert isinstance(diff, FixtureDiff)
        assert diff.is_clean()
        assert diff.files == ()

    def test_one_byte_change_in_journal_is_byte_diff(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        original = (b / "journal.jsonl").read_text()
        (b / "journal.jsonl").write_text(original + '{"phase": "atomic"}\n')
        diff = compare_fixtures(a, b)
        assert not diff.is_clean()
        journal_diff = _find(diff.files, "journal.jsonl")
        assert journal_diff.kind == "byte_diff"
        left_size = len(original.encode())
        right_size = journal_diff.right_bytes
        assert journal_diff.left_bytes == left_size
        assert right_size is not None
        assert right_size > left_size
        first_line = journal_diff.first_diff_line
        assert first_line is not None
        assert first_line >= 1

    def test_missing_file_in_right(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        target = b / "reports" / "assets" / "asset_hd_main.json"
        left_size = (a / "reports" / "assets" / "asset_hd_main.json").stat().st_size
        target.unlink()
        diff = compare_fixtures(a, b)
        entry = _find(diff.files, "reports/assets/asset_hd_main.json")
        assert entry.kind == "missing_in_right"
        assert entry.left_bytes == left_size
        assert entry.right_bytes is None
        assert entry.first_diff_line is None
        assert entry.preview_left is None
        assert entry.preview_right is None

    def test_extra_file_in_right(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        (b / "extra.txt").write_text("extra\n")
        diff = compare_fixtures(a, b)
        entry = _find(diff.files, "extra.txt")
        assert entry.kind == "missing_in_left"
        assert entry.left_bytes is None
        assert entry.right_bytes == len(b"extra\n")

    def test_plan_only_sentinel_omits_created_at_so_runs_match(self, tmp_path: Path) -> None:
        """Plan-only sentinels omit ``created_at`` so two runs are byte-identical.

        WHY: Sprint 4 is plan-only-only. The user spec is explicit that
        ``created_at`` special-casing is out of scope; the right thing
        instead is to confirm the field genuinely is absent so plan-only
        fixtures compare clean without special handling.
        """
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        sentinel_text = (a / ".chaos-librarian-run").read_text()
        assert "created_at" not in sentinel_text
        diff = compare_fixtures(a, b)
        assert diff.is_clean()

    def test_run_replay_compares_oracle_hash_actions(self, tmp_path: Path) -> None:
        """Negative-oracle replay evidence is semantic and must not be dropped."""
        a = _make_run_replay_fixture(
            tmp_path,
            "a",
            oracle_hash_actions=[
                {
                    "event_id": "wrong_hash_001",
                    "action": "wrong_oracle_hash",
                    "target_asset_id": "asset_main",
                    "input_path": "movies-hd/asset_main.mkv",
                    "output_path": "movies-hd/asset_main.mkv",
                    "input_version_id": "version_0001",
                    "output_version_id": "version_0002",
                    "actual_content_hash": "sha256:" + "1" * 64,
                    "reported_content_hash": "sha256:" + "2" * 64,
                    "seed_material": "wrong_oracle_hash_v1:7:wrong_hash_001:asset_main",
                    "duration_ns": 1,
                }
            ],
        )
        b = _make_run_replay_fixture(
            tmp_path,
            "b",
            oracle_hash_actions=[
                {
                    "event_id": "wrong_hash_001",
                    "action": "wrong_oracle_hash",
                    "target_asset_id": "asset_main",
                    "input_path": "movies-hd/asset_main.mkv",
                    "output_path": "movies-hd/asset_main.mkv",
                    "input_version_id": "version_0001",
                    "output_version_id": "version_0002",
                    "actual_content_hash": "sha256:" + "1" * 64,
                    "reported_content_hash": "sha256:" + "3" * 64,
                    "seed_material": "wrong_oracle_hash_v1:7:wrong_hash_001:asset_main",
                    "duration_ns": 99,
                }
            ],
        )

        diff = compare_run_replay(a, b)

        assert _find(diff.files, "materialization.json").kind == "byte_diff"

    def test_run_replay_compares_touch_mtime_by_delta(self, tmp_path: Path) -> None:
        """touch_mtime evidence uses fresh file mtimes; only the requested delta is stable."""
        a = _make_run_replay_fixture(
            tmp_path,
            "a",
            filesystem_actions=[
                {
                    "event_id": "mtime_001",
                    "action": "touch_mtime",
                    "target_asset_id": "asset_main",
                    "from_path": "movies-hd/asset_main.mkv",
                    "to_path": "movies-hd/asset_main.mkv",
                    "content_hash": "sha256:" + "1" * 64,
                    "mtime_before_ns": 1_000,
                    "mtime_after_ns": 3_000,
                    "duration_ns": 1,
                }
            ],
        )
        b = _make_run_replay_fixture(
            tmp_path,
            "b",
            filesystem_actions=[
                {
                    "event_id": "mtime_001",
                    "action": "touch_mtime",
                    "target_asset_id": "asset_main",
                    "from_path": "movies-hd/asset_main.mkv",
                    "to_path": "movies-hd/asset_main.mkv",
                    "content_hash": "sha256:" + "1" * 64,
                    "mtime_before_ns": 10_000,
                    "mtime_after_ns": 12_000,
                    "duration_ns": 99,
                }
            ],
        )

        diff = compare_run_replay(a, b)

        assert diff.is_clean()

    def test_run_replay_detects_touch_mtime_delta_mismatch(self, tmp_path: Path) -> None:
        a = _make_run_replay_fixture(
            tmp_path,
            "a",
            filesystem_actions=[
                {
                    "event_id": "mtime_001",
                    "action": "touch_mtime",
                    "target_asset_id": "asset_main",
                    "from_path": "movies-hd/asset_main.mkv",
                    "to_path": "movies-hd/asset_main.mkv",
                    "mtime_before_ns": 1_000,
                    "mtime_after_ns": 3_000,
                    "duration_ns": 1,
                }
            ],
        )
        b = _make_run_replay_fixture(
            tmp_path,
            "b",
            filesystem_actions=[
                {
                    "event_id": "mtime_001",
                    "action": "touch_mtime",
                    "target_asset_id": "asset_main",
                    "from_path": "movies-hd/asset_main.mkv",
                    "to_path": "movies-hd/asset_main.mkv",
                    "mtime_before_ns": 10_000,
                    "mtime_after_ns": 13_000,
                    "duration_ns": 99,
                }
            ],
        )

        diff = compare_run_replay(a, b)

        assert _find(diff.files, "materialization.json").kind == "byte_diff"


def _find(entries: tuple[FixtureFileDiff, ...], path: str) -> FixtureFileDiff:
    """Return the diff entry for ``path``; raises ``AssertionError`` if absent."""
    for entry in entries:
        if entry.path == path:
            return entry
    raise AssertionError(f"no diff entry for {path!r}; have {[e.path for e in entries]}")


def _make_run_replay_fixture(
    tmp_path: Path,
    name: str,
    *,
    filesystem_actions: list[dict[str, object]] | None = None,
    oracle_hash_actions: list[dict[str, object]] | None = None,
) -> Path:
    out = tmp_path / name
    out.mkdir()
    (out / "library").mkdir()
    (out / "reports").mkdir()
    (out / "manifest.current.json").write_text("{}", encoding="utf-8")
    (out / "journal.jsonl").write_text("", encoding="utf-8")
    (out / "replay.json").write_text(
        (
            '{"scenario":"s","run_id":"r","resolved_seed":7,'
            '"applied_events":1,"journal_digest":"d","execution_mode":"run",'
            '"content_sources":[]}'
        ),
        encoding="utf-8",
    )
    materialization = {
        "outcome": "success",
        "execution_mode": "run",
        "content_sources": [],
        "materialized": [],
        "failures": [],
        "filesystem_actions": filesystem_actions or [],
        "media_actions": [],
        "corruption_actions": [],
        "oracle_hash_actions": oracle_hash_actions or [],
    }
    (out / "materialization.json").write_text(
        json.dumps(materialization),
        encoding="utf-8",
    )
    return out
