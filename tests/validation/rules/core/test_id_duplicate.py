"""Per-rule tests for ``rule_id_duplicate`` (E_ID_DUPLICATE).

Each test class names the WHY (per CLAUDE.md Rule 9): what would break in
downstream sprints (plan, materialize, run, journal, manifest) if this
semantic rule did not exist.
"""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRule1IdDuplicateGlobalAssets:
    """Duplicate asset IDs across different bundles are an error.

    WHY: timeline `target:` references resolve against a flat asset
    namespace (see manifest.py's ManifestAsset list); two assets sharing
    an ID would make that lookup ambiguous and would collide in
    manifest.json. Closes Codex review finding #1.
    """

    def test_duplicate_asset_id_across_bundles(
        self, minimal_scenario, empty_index, as_list
    ) -> None:
        raw = minimal_scenario()
        # Add a second variant whose bundle contains an asset with the same id.
        variants = as_list(as_list(raw["movies"])[0]["variants"])
        variants.append(
            {
                "id": "v2",
                "label": "l2",
                "bundle": {
                    "id": "b2",
                    "assets": [
                        {
                            "id": "a",  # duplicate of movies[0]...assets[0].id
                            "role": "primary_video",
                            "container": "mkv",
                            "duration_seconds": 1,
                        }
                    ],
                },
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        dup_issues = [i for i in collector.issues if i.code == codes.E_ID_DUPLICATE]
        assert len(dup_issues) == 1
        assert "asset_id" in dup_issues[0].message
        assert "'a'" in dup_issues[0].message

    def test_duplicate_asset_id_within_bundle(
        self, minimal_scenario, empty_index, as_list, as_dict
    ) -> None:
        """Per-bundle duplicates still fire — global uniqueness subsumes scoped."""
        raw = minimal_scenario()
        bundle = as_dict(as_list(as_list(raw["movies"])[0]["variants"])[0]["bundle"])
        assets = as_list(bundle["assets"])
        assets.append(
            {
                "id": "a",
                "role": "secondary_video",
                "container": "mkv",
                "duration_seconds": 1,
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_ID_DUPLICATE for i in collector.issues)


class TestRule1IdDuplicateGlobalVariants:
    """Duplicate variant IDs across different movies are an error.

    WHY: variants are oracle keys in the manifest (one ManifestVariant per
    id); collisions would make plan/materialize ambiguous.
    """

    def test_duplicate_variant_id_across_movies(
        self, minimal_scenario, empty_index, as_list
    ) -> None:
        raw = minimal_scenario()
        movies = as_list(raw["movies"])
        movies.append(
            {
                "id": "movie_two",
                "title": "t2",
                "layout": "movie_flat",
                "variants": [
                    {
                        "id": "v",  # collides with movies[0].variants[0].id
                        "label": "l",
                        "bundle": {"id": "b3", "assets": []},
                    }
                ],
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "variant_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateGlobalBundles:
    """Duplicate bundle IDs across different variants are an error.

    WHY: bundle IDs are journal keys (ManifestBundle list); collisions
    would corrupt durable identity tracking.
    """

    def test_duplicate_bundle_id_across_variants(
        self, minimal_scenario, empty_index, as_list
    ) -> None:
        raw = minimal_scenario()
        variants = as_list(as_list(raw["movies"])[0]["variants"])
        variants.append(
            {
                "id": "v2",
                "label": "l",
                "bundle": {"id": "b", "assets": []},  # duplicate bundle id
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "bundle_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateTopLevel:
    """Duplicate root_id, movie_id, timeline_id at the top level are errors.

    WHY: these are flat namespaces; collisions would ambiguate references
    in subsequent semantic passes.
    """

    def test_duplicate_root_id(self, minimal_scenario, empty_index, as_list, as_dict) -> None:
        raw = minimal_scenario()
        roots = as_list(as_dict(raw["library"])["roots"])
        roots.append({"id": "r", "path": "r2"})
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "root_id" in i.message for i in collector.issues
        )

    def test_duplicate_movie_id(self, minimal_scenario, empty_index, as_list) -> None:
        raw = minimal_scenario()
        movies = as_list(raw["movies"])
        movies.append(
            {"id": "movie_t", "title": "t2", "layout": "movie_flat", "variants": []},
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "movie_id" in i.message for i in collector.issues
        )

    def test_duplicate_timeline_id(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e1", "at": "2s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "timeline_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateHierarchyEntities:
    """Duplicate hierarchy entity IDs are global collisions.

    WHY: hierarchy actions and reports address these entities by flat IDs,
    so cross-tree duplicates would make target resolution ambiguous.
    """

    def test_duplicate_series_id(self, series_scenario, empty_index, as_list) -> None:
        raw = series_scenario()
        series = as_list(raw["series"])
        series.append(
            {
                "id": "series_starline",
                "title": "Starline Again",
                "layout": "season_folders",
                "episode_naming": "sxxexx_title",
                "seasons": [],
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "series_id" in i.message for i in collector.issues
        )

    def test_duplicate_season_id(self, series_scenario, empty_index, as_list) -> None:
        raw = series_scenario()
        series = as_list(raw["series"])[0]
        seasons = as_list(series["seasons"])
        seasons.append(
            {"id": "season_one", "season_number": 2, "title": "Season 2", "episodes": []}
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "season_id" in i.message for i in collector.issues
        )

    def test_duplicate_artist_id(self, music_scenario, empty_index, as_list) -> None:
        raw = music_scenario()
        artists = as_list(raw["artists"])
        artists.append(
            {
                "id": "artist_north",
                "name": "North Index Again",
                "layout": "artist_album_disc",
                "track_naming": "track_number_title",
                "albums": [],
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "artist_id" in i.message for i in collector.issues
        )

    def test_duplicate_disc_id(self, music_scenario, empty_index, as_list) -> None:
        raw = music_scenario()
        artist = as_list(raw["artists"])[0]
        album = as_list(artist["albums"])[0]
        discs = as_list(album["discs"])
        discs.append({"id": "disc_one", "disc_number": 2, "tracks": []})
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "disc_id" in i.message for i in collector.issues
        )


class TestRule1IdDuplicateNoFalsePositives:
    """A minimal valid scenario produces zero E_ID_DUPLICATE issues.

    WHY: rule must not over-fire on clean input. The end-to-end valid-
    fixture smoke check is in tests/validation/test_invalid_corpus.py
    (Task 14).
    """

    def test_minimal_scenario_no_duplicates(self, minimal_scenario, empty_index) -> None:
        collector = IssueCollector()
        run_semantic_pass(minimal_scenario(), empty_index, collector)
        assert not any(i.code == codes.E_ID_DUPLICATE for i in collector.issues)
