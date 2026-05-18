"""Per-rule semantic tests. One class per E_* code.

Each rule test names the WHY (per CLAUDE.md Rule 9): what would break in
downstream sprints (plan, materialize, run, journal, manifest) if this
semantic rule did not exist.
"""

from __future__ import annotations

from typing import cast

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _empty_index() -> LineIndex:
    return LineIndex()


def _as_list(node: object) -> list[dict[str, object]]:
    """Narrow ``object`` to a typed list for test-site subscripting.

    The scenario tree returned by ``_minimal_scenario`` types everything as
    ``object`` (matching what semantic rules see). Tests know the concrete
    shape and use this helper to drill in without sprinkling casts.
    """
    return cast("list[dict[str, object]]", node)


def _as_dict(node: object) -> dict[str, object]:
    """Narrow ``object`` to a typed dict; mirror of ``_as_list``."""
    return cast("dict[str, object]", node)


def _minimal_scenario(
    timeline: list[dict[str, object]] | None = None,
    **overrides: object,
) -> dict[str, object]:
    """Build a minimal valid-shape scenario. Overrides can add duplicates."""
    base: dict[str, object] = {
        "schema_version": 1,
        "scenario_id": "t",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r", "path": "r"}]},
        "works": [
            {
                "id": "w",
                "title": "t",
                "variants": [
                    {
                        "id": "v",
                        "label": "l",
                        "bundle": {
                            "id": "b",
                            "assets": [
                                {
                                    "id": "a",
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
        "timeline": timeline or [],
    }
    base.update(overrides)
    return base


class TestRule1IdDuplicateGlobalAssets:
    """Duplicate asset IDs across different bundles are an error.

    WHY: timeline `target:` references resolve against a flat asset
    namespace (see manifest.py's ManifestAsset list); two assets sharing
    an ID would make that lookup ambiguous and would collide in
    manifest.json. Closes Codex review finding #1.
    """

    def test_duplicate_asset_id_across_bundles(self) -> None:
        raw = _minimal_scenario()
        # Add a second variant whose bundle contains an asset with the same id.
        variants = _as_list(_as_list(raw["works"])[0]["variants"])
        variants.append(
            {
                "id": "v2",
                "label": "l2",
                "bundle": {
                    "id": "b2",
                    "assets": [
                        {
                            "id": "a",  # duplicate of works[0].variants[0].bundle.assets[0].id
                            "role": "primary_video",
                            "container": "mkv",
                            "duration_seconds": 1,
                        }
                    ],
                },
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        dup_issues = [i for i in collector.issues if i.code == codes.E_ID_DUPLICATE]
        assert len(dup_issues) == 1
        assert "asset_id" in dup_issues[0].message
        assert "'a'" in dup_issues[0].message

    def test_duplicate_asset_id_within_bundle(self) -> None:
        """Per-bundle duplicates still fire — global uniqueness subsumes scoped."""
        raw = _minimal_scenario()
        bundle = _as_dict(_as_list(_as_list(raw["works"])[0]["variants"])[0]["bundle"])
        assets = _as_list(bundle["assets"])
        assets.append(
            {
                "id": "a",
                "role": "secondary_video",
                "container": "mkv",
                "duration_seconds": 1,
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_ID_DUPLICATE for i in collector.issues)


class TestRule1IdDuplicateGlobalVariants:
    """Duplicate variant IDs across different works are an error.

    WHY: variants are oracle keys in the manifest (one ManifestVariant per
    id); collisions would make plan/materialize ambiguous.
    """

    def test_duplicate_variant_id_across_works(self) -> None:
        raw = _minimal_scenario()
        works = _as_list(raw["works"])
        works.append(
            {
                "id": "w2",
                "title": "t2",
                "variants": [
                    {
                        "id": "v",  # collides with works[0].variants[0].id
                        "label": "l",
                        "bundle": {"id": "b3", "assets": []},
                    }
                ],
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "variant_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateGlobalBundles:
    """Duplicate bundle IDs across different variants are an error.

    WHY: bundle IDs are journal keys (ManifestBundle list); collisions
    would corrupt durable identity tracking.
    """

    def test_duplicate_bundle_id_across_variants(self) -> None:
        raw = _minimal_scenario()
        variants = _as_list(_as_list(raw["works"])[0]["variants"])
        variants.append(
            {
                "id": "v2",
                "label": "l",
                "bundle": {"id": "b", "assets": []},  # duplicate bundle id
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "bundle_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateTopLevel:
    """Duplicate root_id, work_id, timeline_id at the top level are errors.

    WHY: these are flat namespaces; collisions would ambiguate references
    in subsequent semantic passes.
    """

    def test_duplicate_root_id(self) -> None:
        raw = _minimal_scenario()
        roots = _as_list(_as_dict(raw["library"])["roots"])
        roots.append({"id": "r", "path": "r2"})
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "root_id" in i.message for i in collector.issues
        )

    def test_duplicate_work_id(self) -> None:
        raw = _minimal_scenario()
        works = _as_list(raw["works"])
        works.append(
            {"id": "w", "title": "t2", "variants": []},
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "work_id" in i.message for i in collector.issues
        )

    def test_duplicate_timeline_id(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e1", "at": "2s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "timeline_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateNoFalsePositives:
    """A minimal valid scenario produces zero E_ID_DUPLICATE issues.

    WHY: rule must not over-fire on clean input. The end-to-end valid-
    fixture smoke check is in tests/validation/test_invalid_corpus.py
    (Task 14).
    """

    def test_minimal_scenario_no_duplicates(self) -> None:
        collector = IssueCollector()
        run_semantic_pass(_minimal_scenario(), _empty_index(), collector)
        assert not any(i.code == codes.E_ID_DUPLICATE for i in collector.issues)


class TestRule2PathDuplicate:
    """Two library roots sharing the same path emit a WARNING, not an ERROR.

    WHY: duplicate paths under distinct IDs are well-defined (alias) but
    almost always a typo; flagging without flipping ok lets validate
    still pass on legitimate aliases.
    """

    def test_warning_severity_no_exit_flip(self) -> None:
        raw = _minimal_scenario()
        library = _as_dict(raw["library"])
        roots = _as_list(library["roots"])
        roots.append({"id": "r2", "path": "r"})  # same path
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        warnings = [i for i in collector.issues if i.code == codes.E_PATH_DUPLICATE]
        assert len(warnings) == 1
        assert warnings[0].severity.value == "warning"

    def test_distinct_paths_no_warning(self) -> None:
        raw = _minimal_scenario()
        library = _as_dict(raw["library"])
        roots = _as_list(library["roots"])
        roots.append({"id": "r2", "path": "r2"})
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_PATH_DUPLICATE for i in collector.issues)


class TestRule3DurationSyntax:
    """Every duration string in the timeline must parse.

    WHY: bad durations silently coerce to 0 or crash downstream when
    the journal converts them to logical_time_ns; flagging here keeps
    the contract of "validated scenarios always have parseable times."
    """

    def test_bad_at_field(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "not-a-duration", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_DURATION_SYNTAX for i in collector.issues)

    def test_bad_slow_copy_duration(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_DURATION_SYNTAX and "duration" in (i.path or "")
            for i in collector.issues
        )

    def test_valid_durations_no_issues(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1m30s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_DURATION_SYNTAX for i in collector.issues)


class TestRule4TargetUnknown:
    """Every timeline target: must resolve to a real asset id.

    WHY: an unresolved target would crash the materializer at runtime;
    catching it at validate avoids polluting the journal with a half-
    applied event.
    """

    def test_unknown_target(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "ghost"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_TARGET_UNKNOWN and "ghost" in i.message for i in collector.issues
        )

    def test_known_target_passes(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_TARGET_UNKNOWN for i in collector.issues)

    def test_slow_copy_commit_has_no_target_so_no_check(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_TARGET_UNKNOWN for i in collector.issues)


class TestRule5aSlowCopyUnpaired:
    """Structural pairing for slow_copy_start / slow_copy_commit.

    WHY: an orphan commit applies nothing (the temp file does not exist);
    an orphan start leaves a permanent temp file in the library.
    """

    def test_commit_without_start(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "c1", "at": "1s", "action": "slow_copy_commit", "for": "ghost"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_start_without_commit(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_two_commits_for_one_start(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_correctly_paired_no_issue(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)


class TestRule5bSlowCopyTiming:
    """For each matched pair, commit.at must equal start.at + start.duration.

    WHY: the design spec says the temp file is "grown over the declared
    duration: between the two events." Any drift would mean either an
    idle gap (commit too late) or premature commit (impossible). Closes
    Codex review finding #2.
    """

    def test_commit_too_early_is_error(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_commit_too_late_is_error(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_exact_match_no_issue(self) -> None:
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_skipped_when_durations_unparseable(self) -> None:
        """Rule 3 already flags; Rule 5b must not double-report."""
        raw = _minimal_scenario(
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
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)


class TestRule6PathContainment:
    """Every scenario path must pass the containment helper.

    WHY: a path that resolves outside the library root is a filesystem-
    safety violation; the runtime (plan/materialize) would refuse to
    write there. Catching at validate prevents partial runs.
    """

    def test_absolute_root_path_rejected(self) -> None:
        raw = _minimal_scenario()
        library = _as_dict(raw["library"])
        roots = _as_list(library["roots"])
        first_root = _as_dict(roots[0])
        first_root["path"] = "/etc/passwd"
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_dotdot_escape_in_to(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "../../etc/passwd",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_temp_path_checked(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "movies/x.mkv",
                    "temp_path": "/tmp/x.part",  # absolute — rejected
                    "duration": "1s",
                },
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        # at least one E_PATH_CONTAINMENT against the temp_path
        assert any(
            i.code == codes.E_PATH_CONTAINMENT and "temp_path" in (i.path or "")
            for i in collector.issues
        )

    def test_valid_relative_paths_no_issue(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "movies-hd/Foo.mkv",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)
