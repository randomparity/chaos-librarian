"""Tests for chaos_librarian.engine.diff.compare_fixtures."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.engine.diff import (
    FixtureDiff,
    FixtureFileDiff,
    compare_fixtures,
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

    def test_sentinel_created_at_difference_trivially_clean_in_plan_only(
        self, tmp_path: Path
    ) -> None:
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


def _find(entries: tuple[FixtureFileDiff, ...], path: str) -> FixtureFileDiff:
    """Return the diff entry for ``path``; raises ``AssertionError`` if absent."""
    for entry in entries:
        if entry.path == path:
            return entry
    raise AssertionError(f"no diff entry for {path!r}; have {[e.path for e in entries]}")
