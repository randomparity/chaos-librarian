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


def _scenario_with_movies_hd(
    minimal_scenario,
    timeline: list[dict[str, object]],
) -> dict[str, object]:
    """Build a Rule 5c scenario whose primary root is ``library/movies-hd``.

    Rule 5c joins each slow-copy target against the hierarchy-rendered
    initial path. The default ``minimal_scenario`` fixture uses ``path: r``,
    so this helper overrides the movie hierarchy to keep the rendered path
    aligned with the timeline targets.
    """
    return minimal_scenario(
        timeline=timeline,
        library={"roots": [{"id": "movies-hd", "path": "library/movies-hd"}]},
        movies=[
            {
                "id": "movie_t",
                "title": "t",
                "layout": "movie_flat",
                "variants": [
                    {
                        "id": "v",
                        "label": "l",
                        "bundle": {
                            "id": "b",
                            "assets": [
                                {
                                    "id": "asset_hd_main",
                                    "role": "primary_video",
                                    "container": "mkv",
                                    "duration_seconds": 1,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    )


class TestRule5cSlowCopyPathCollision:
    """Reject ``temp_path`` that collides with the final or initial path.

    WHY: phase-B commit unlinks ``initial_path`` and then ``replace()``s
    ``temp_path → final_path``. If ``temp_path == to`` the multi-phase
    visibility contract collapses; if ``temp_path == initial_path`` the
    unlink wipes the temp before the replace runs. Both are unrecoverable
    in the materializer, so we surface them at validation time.
    """

    def test_slow_copy_rejects_temp_equals_final(self, minimal_scenario, empty_index) -> None:
        raw = _scenario_with_movies_hd(
            minimal_scenario,
            timeline=[
                {
                    "id": "scs",
                    "at": "0ns",
                    "action": "slow_copy_start",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/final.mkv",
                    "temp_path": "library/movies-hd/final.mkv",
                    "duration": "1ns",
                },
                {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        collisions = [i for i in collector.issues if i.code == codes.E_SLOW_COPY_PATH_COLLISION]
        assert collisions, (
            f"expected E_SLOW_COPY_PATH_COLLISION in {[i.code for i in collector.issues]}"
        )
        assert "temp_path equals to" in collisions[0].message

    def test_slow_copy_rejects_temp_equals_initial_path(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = _scenario_with_movies_hd(
            minimal_scenario,
            timeline=[
                {
                    "id": "scs",
                    "at": "0ns",
                    "action": "slow_copy_start",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/final.mkv",
                    "temp_path": "library/movies-hd/t - l.mkv",
                    "duration": "1ns",
                },
                {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        collisions = [i for i in collector.issues if i.code == codes.E_SLOW_COPY_PATH_COLLISION]
        assert collisions, (
            f"expected E_SLOW_COPY_PATH_COLLISION in {[i.code for i in collector.issues]}"
        )
        assert "current path" in collisions[0].message.lower()

    def test_slow_copy_path_collision_allows_distinct_paths(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = _scenario_with_movies_hd(
            minimal_scenario,
            timeline=[
                {
                    "id": "scs",
                    "at": "0ns",
                    "action": "slow_copy_start",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/final.mkv",
                    "temp_path": "library/movies-hd/temp.mkv",
                    "duration": "1ns",
                },
                {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SLOW_COPY_PATH_COLLISION for i in collector.issues)

    def test_slow_copy_rejects_temp_equals_initial_via_dot_segment(
        self, minimal_scenario, empty_index
    ) -> None:
        """A ``.`` segment in temp_path must not let it slip past the rule.

        Without normalization, raw ``==`` would treat
        ``library/./movies-hd/...`` as distinct from ``library/movies-hd/...``
        even though they describe the same on-disk path.
        """
        raw = _scenario_with_movies_hd(
            minimal_scenario,
            timeline=[
                {
                    "id": "scs",
                    "at": "0ns",
                    "action": "slow_copy_start",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/final.mkv",
                    "temp_path": "library/./movies-hd/t - l.mkv",
                    "duration": "1ns",
                },
                {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_PATH_COLLISION for i in collector.issues)

    def test_slow_copy_rejects_temp_equals_hierarchy_mutated_current_path(
        self, series_scenario, empty_index
    ) -> None:
        raw = series_scenario(
            timeline=[
                {
                    "id": "renumber",
                    "at": "1s",
                    "action": "renumber_episode",
                    "target": "episode_one",
                    "episode_number": 2,
                },
                {
                    "id": "copy",
                    "at": "2s",
                    "action": "slow_copy_start",
                    "target": "asset_episode",
                    "to": "TV/Starline/Season 01/final.mkv",
                    "temp_path": ("TV/Starline/Season 01/Starline - S01E02 - Pilot - HD.mkv"),
                    "duration": "1s",
                },
                {"id": "commit", "at": "3s", "action": "slow_copy_commit", "for": "copy"},
            ]
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)

        assert any(i.code == codes.E_SLOW_COPY_PATH_COLLISION for i in collector.issues)

    def test_slow_copy_allows_temp_equal_stale_pre_hierarchy_path(
        self, series_scenario, empty_index
    ) -> None:
        raw = series_scenario(
            timeline=[
                {
                    "id": "renumber",
                    "at": "1s",
                    "action": "renumber_episode",
                    "target": "episode_one",
                    "episode_number": 2,
                },
                {
                    "id": "copy",
                    "at": "2s",
                    "action": "slow_copy_start",
                    "target": "asset_episode",
                    "to": "TV/Starline/Season 01/final.mkv",
                    "temp_path": ("TV/Starline/Season 01/Starline - S01E01 - Pilot - HD.mkv"),
                    "duration": "1s",
                },
                {"id": "commit", "at": "3s", "action": "slow_copy_commit", "for": "copy"},
            ]
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)

        assert not any(i.code == codes.E_SLOW_COPY_PATH_COLLISION for i in collector.issues)

    def test_slow_copy_allows_temp_equal_to_stale_initial_path_after_move(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = _scenario_with_movies_hd(
            minimal_scenario,
            timeline=[
                {
                    "id": "move",
                    "at": "0ns",
                    "action": "move_asset",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/current.mkv",
                },
                {
                    "id": "scs",
                    "at": "1ns",
                    "action": "slow_copy_start",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/final.mkv",
                    "temp_path": "library/movies-hd/t - l.mkv",
                    "duration": "1ns",
                },
                {"id": "scc", "at": "2ns", "action": "slow_copy_commit", "for": "scs"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_SLOW_COPY_PATH_COLLISION for i in collector.issues)

    def test_slow_copy_rejects_temp_equal_to_current_path_after_move(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = _scenario_with_movies_hd(
            minimal_scenario,
            timeline=[
                {
                    "id": "move",
                    "at": "0ns",
                    "action": "move_asset",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/current.mkv",
                },
                {
                    "id": "scs",
                    "at": "1ns",
                    "action": "slow_copy_start",
                    "target": "asset_hd_main",
                    "to": "library/movies-hd/final.mkv",
                    "temp_path": "library/movies-hd/current.mkv",
                    "duration": "1ns",
                },
                {"id": "scc", "at": "2ns", "action": "slow_copy_commit", "for": "scs"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_SLOW_COPY_PATH_COLLISION for i in collector.issues)
