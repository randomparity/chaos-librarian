"""Per-rule tests for ``rule_timeline_lifecycle`` (E_LIFECYCLE_INVALID)."""

from __future__ import annotations

import pytest

from chaos_librarian.validation import codes
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.timeline_lifecycle import rule_timeline_lifecycle
from chaos_librarian.validation.semantic import run_semantic_pass


class TestRuleTimelineLifecycle:
    """The lifecycle rule rejects sequences that the engine cannot honor.

    WHY: shape-valid timelines used to crash the engine with unstructured
    ``ValueError``s. The rule keeps the failure mode inside the validation
    pipeline so the CLI emits an ``E_LIFECYCLE_INVALID`` report and exits 3.
    """

    def test_add_on_placed_asset_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "0", "action": "add_file", "target": "a", "to": "r/a.mkv"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(i.code == codes.E_LIFECYCLE_INVALID for i in collector.issues)

    def test_move_after_delete_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "0", "action": "delete_file", "target": "a"},
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "move_asset",
                    "target": "a",
                    "to": "r/x.mkv",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        codes_found = [i.code for i in collector.issues]
        assert codes.E_LIFECYCLE_INVALID in codes_found

    def test_double_slow_copy_start_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "c1",
                    "at": "0",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "r/x.mkv",
                    "temp_path": "r/x.mkv.part",
                    "duration": "2s",
                },
                {
                    "id": "c2",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "r/y.mkv",
                    "temp_path": "r/y.mkv.part",
                    "duration": "2s",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert any(
            i.code == codes.E_LIFECYCLE_INVALID and "pending" in i.message for i in collector.issues
        )

    def test_happy_path_unaffected(self, minimal_scenario, empty_index) -> None:
        """A normal move/rename sequence must NOT trip the rule."""
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "move_asset",
                    "target": "a",
                    "to": "r/x.mkv",
                },
                {
                    "id": "e2",
                    "at": "2s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "r/y.mkv",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_LIFECYCLE_INVALID for i in collector.issues)


class TestRuleLifecyclePostDeleteMutations:
    """Lifecycle rule rejects mutations on a deleted asset.

    WHY: shape-valid timelines that target an unplaced asset crash the
    engine inside the per-action handler with an unstructured KeyError on
    ``_asset_to_location`` / ``_asset_to_version``. Catching these in
    validation turns those crashes into a structured E_LIFECYCLE_INVALID
    report. Closes Codex adversarial-review finding 2 (lifecycle gaps).
    """

    def test_reencode_video_after_delete_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "0", "action": "delete_file", "target": "a"},
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "reencode_video",
                    "target": "a",
                    "resolution": "720p",
                    "codec": "h264",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("reencode_video" in i.message and "unplaced" in i.message for i in issues)

    def test_reencode_audio_after_delete_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "0", "action": "delete_file", "target": "a"},
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "reencode_audio",
                    "target": "a",
                    "from_channels": "stereo",
                    "to_channels": "5.1",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("reencode_audio" in i.message and "unplaced" in i.message for i in issues)

    def test_create_sidecar_after_delete_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "e1", "at": "0", "action": "delete_file", "target": "a"},
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a",
                    "to": "r/a.eng.srt",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("create_sidecar" in i.message and "unplaced" in i.message for i in issues)


class TestRuleLifecycleDuringPendingSlowCopy:
    """Lifecycle rule rejects path-changing mutations while a slow_copy is pending.

    WHY: ``slow_copy_start`` registers the location id in
    ``state.pending_slow_copies``; commit reads ``previous.asset_id`` from
    that location. Deleting (or moving / renaming) the asset between start
    and commit either pops the entry the commit needs or invalidates its
    stored path — engine-side this is a ``KeyError`` inside
    ``_handle_slow_copy_commit``. Closes Codex adversarial-review finding 2.
    """

    @staticmethod
    def _slow_copy_start() -> dict[str, object]:
        return {
            "id": "s1",
            "at": "0",
            "action": "slow_copy_start",
            "target": "a",
            "to": "r/a.mkv",
            "temp_path": "r/a.mkv.part",
            "duration": "2s",
        }

    @staticmethod
    def _slow_copy_commit() -> dict[str, object]:
        return {"id": "c1", "at": "5s", "action": "slow_copy_commit", "for": "s1"}

    def test_delete_during_slow_copy_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                self._slow_copy_start(),
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
                self._slow_copy_commit(),
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("delete_file" in i.message and "pending slow_copy" in i.message for i in issues)

    def test_move_during_slow_copy_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                self._slow_copy_start(),
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "move_asset",
                    "target": "a",
                    "to": "r/b.mkv",
                },
                self._slow_copy_commit(),
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("move_asset" in i.message and "pending slow_copy" in i.message for i in issues)

    def test_rename_during_slow_copy_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                self._slow_copy_start(),
                {
                    "id": "e2",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "r/b.mkv",
                },
                self._slow_copy_commit(),
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("rename_file" in i.message and "pending slow_copy" in i.message for i in issues)

    def test_back_to_back_starts_after_commit_allowed(self, minimal_scenario, empty_index) -> None:
        """A clean start/commit/start/commit pair on the same asset is legal."""
        raw = minimal_scenario(
            timeline=[
                self._slow_copy_start(),
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
                {
                    "id": "s2",
                    "at": "3s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "r/a2.mkv",
                    "temp_path": "r/a2.mkv.part",
                    "duration": "1s",
                },
                {"id": "c2", "at": "4s", "action": "slow_copy_commit", "for": "s2"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_LIFECYCLE_INVALID for i in collector.issues)


class TestRuleLifecycleArchiveFile:
    """Lifecycle rule covers ``archive_file`` as a path-mutating passthrough.

    WHY: ``archive_file`` keeps the asset placed but moves bytes on disk
    (location-id swap to the archive root). The engine's handler would
    KeyError on ``state._asset_to_location`` for an unplaced asset, and a
    pending ``slow_copy_start`` references the same location id the archive
    would relocate. Both failure modes belong in validation, not engine.
    """

    def test_archive_file_on_unplaced_asset_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "ev_del", "at": "0", "action": "delete_file", "target": "a"},
                {"id": "ev_arch", "at": "1s", "action": "archive_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("archive_file" in i.message and "unplaced" in i.message for i in issues)

    def test_archive_file_keeps_asset_placed(self, minimal_scenario, empty_index) -> None:
        """archive_file is a passthrough — the asset remains placed afterward."""
        raw = minimal_scenario(
            timeline=[
                {"id": "ev_arch", "at": "0", "action": "archive_file", "target": "a"},
                {
                    "id": "ev_move",
                    "at": "1s",
                    "action": "move_asset",
                    "target": "a",
                    "to": "r/new.mkv",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        assert not any(i.code == codes.E_LIFECYCLE_INVALID for i in collector.issues)

    def test_archive_file_on_pending_slow_copy_emits(self, minimal_scenario, empty_index) -> None:
        raw = minimal_scenario(
            timeline=[
                {
                    "id": "scs",
                    "at": "0",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "r/final.mkv",
                    "temp_path": "r/temp.mkv",
                    "duration": "1s",
                },
                {"id": "ev_arch", "at": "0", "action": "archive_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("archive_file" in i.message and "pending slow_copy" in i.message for i in issues)


class TestRuleLifecycleMoveBetweenRoots:
    """Lifecycle rule covers ``move_between_roots`` as a path-mutating passthrough.

    WHY: parallel to ``archive_file`` — the engine relocates bytes between
    two roots, so an unplaced target or a pending ``slow_copy`` would crash
    the handler. Validation rejects both upfront with E_LIFECYCLE_INVALID.
    """

    def test_move_between_roots_on_unplaced_asset_emits(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            library={"roots": [{"id": "r", "path": "r"}, {"id": "r2", "path": "r2"}]},
            timeline=[
                {"id": "ev_del", "at": "0", "action": "delete_file", "target": "a"},
                {
                    "id": "ev_mbr",
                    "at": "1s",
                    "action": "move_between_roots",
                    "target": "a",
                    "from_root_id": "r",
                    "to_root_id": "r2",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any("move_between_roots" in i.message and "unplaced" in i.message for i in issues)

    def test_move_between_roots_on_pending_slow_copy_emits(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            library={"roots": [{"id": "r", "path": "r"}, {"id": "r2", "path": "r2"}]},
            timeline=[
                {
                    "id": "scs",
                    "at": "0",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "r/final.mkv",
                    "temp_path": "r/temp.mkv",
                    "duration": "1s",
                },
                {
                    "id": "ev_mbr",
                    "at": "0",
                    "action": "move_between_roots",
                    "target": "a",
                    "from_root_id": "r",
                    "to_root_id": "r2",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, empty_index, collector)
        issues = [i for i in collector.issues if i.code == codes.E_LIFECYCLE_INVALID]
        assert any(
            "move_between_roots" in i.message and "pending slow_copy" in i.message for i in issues
        )


class TestSprint7LifecycleExtensions:
    """Sprint 7 adds 6 new actions to the simulator; all 6 require placed targets.

    REMUX, EDIT_METADATA, EMBED_SUBTITLE, EXTRACT_SUBTITLE join
    _PATH_MUTATING_PASSTHROUGH (rejected against pending slow_copy).
    UPDATE_SIDECAR and REMOVE_SIDECAR are EXCLUDED — they don't touch
    the asset.
    """

    def test_remux_container_on_unplaced_asset_rejected(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            asset_id="asset_main",
            timeline=[
                {"id": "e0", "at": "1s", "action": "delete_file", "target": "asset_main"},
                {
                    "id": "e1",
                    "at": "2s",
                    "action": "remux_container",
                    "target": "asset_main",
                    "to_container": "mp4",
                },
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)

    @pytest.mark.parametrize(
        ("action", "fields"),
        [
            ("remux_container", {"to_container": "mp4"}),
            ("edit_metadata", {"fields": {"k": "v"}}),
            ("embed_subtitle", {"sidecar_path": "asset_main.eng.srt"}),
            ("extract_subtitle", {"to": "asset_main.fra.srt", "language": "fra"}),
        ],
    )
    def test_slow_copy_forbidden_action(
        self, minimal_scenario, empty_index, action, fields
    ) -> None:
        raw = minimal_scenario(
            asset_id="asset_main",
            asset_subtitles=[{"codec": "srt", "language": "eng", "mode": "sidecar"}],
            timeline=[
                {
                    "id": "e_sc",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "asset_main",
                    "to": "asset_main.mkv",
                    "temp_path": "asset_main.mkv.copying",
                    "duration": "5s",
                },
                {
                    "id": "e_op",
                    "at": "2s",
                    "action": action,
                    "target": "asset_main",
                    **fields,
                },
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert any(i.code == E_LIFECYCLE_INVALID for i in collector.issues), (
            f"action {action} during pending slow_copy must be rejected"
        )

    def test_update_sidecar_during_pending_slow_copy_valid(
        self, minimal_scenario, empty_index
    ) -> None:
        # UPDATE_SIDECAR is intentionally NOT in _PATH_MUTATING_PASSTHROUGH
        # — it touches a sidecar file, not the asset bytes.
        raw = minimal_scenario(
            asset_id="asset_main",
            timeline=[
                {
                    "id": "e_cs",
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": "asset_main",
                    "to": "asset_main.eng.srt",
                    "language": "eng",
                },
                {
                    "id": "e_sc",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "asset_main",
                    "to": "asset_main.mkv",
                    "temp_path": "asset_main.mkv.copying",
                    "duration": "5s",
                },
                {
                    "id": "e_us",
                    "at": "2s",
                    "action": "update_sidecar",
                    "target": "asset_main",
                    "sidecar_path": "asset_main.eng.srt",
                },
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        # Lifecycle rule should NOT flag update_sidecar during slow_copy.
        assert not any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)

    def test_remove_sidecar_during_pending_slow_copy_valid(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            asset_id="asset_main",
            timeline=[
                {
                    "id": "e_cs",
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": "asset_main",
                    "to": "asset_main.eng.srt",
                    "language": "eng",
                },
                {
                    "id": "e_sc",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "asset_main",
                    "to": "asset_main.mkv",
                    "temp_path": "asset_main.mkv.copying",
                    "duration": "5s",
                },
                {
                    "id": "e_rs",
                    "at": "2s",
                    "action": "remove_sidecar",
                    "target": "asset_main",
                    "sidecar_path": "asset_main.eng.srt",
                },
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert not any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)

    def test_embed_subtitle_on_missing_sidecar_emits_lifecycle_invalid(
        self, minimal_scenario, empty_index
    ) -> None:
        # Sprint 7 spec: lifecycle rule covers dynamic case (sidecar removed
        # earlier in timeline). Static case is rule_sidecar_target.
        raw = minimal_scenario(
            asset_id="asset_main",
            asset_subtitles=[{"codec": "srt", "language": "eng", "mode": "sidecar"}],
            timeline=[
                {
                    "id": "e_rs",
                    "at": "1s",
                    "action": "remove_sidecar",
                    "target": "asset_main",
                    "sidecar_path": "asset_main.eng.srt",
                },
                {
                    "id": "e_es",
                    "at": "2s",
                    "action": "embed_subtitle",
                    "target": "asset_main",
                    "sidecar_path": "asset_main.eng.srt",
                },
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)


class TestSprint10CorruptionLifecycle:
    """Corruption mutates asset bytes and requires a placed, non-copying target."""

    def test_corruption_after_delete_emits_lifecycle_invalid(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            profiles=["malformed-media"],
            timeline=[
                {"id": "ev_del", "at": "0s", "action": "delete_file", "target": "a"},
                {
                    "id": "corrupt_header_001",
                    "at": "1s",
                    "action": "corrupt_container_header",
                    "target": "a",
                },
            ],
        )
        collector = IssueCollector()

        rule_timeline_lifecycle(raw, empty_index, collector)

        issues = [i for i in collector.issues if i.code == E_LIFECYCLE_INVALID]
        assert any(
            "corrupt_container_header" in i.message and "unplaced" in i.message for i in issues
        )

    def test_corruption_during_slow_copy_emits_lifecycle_invalid(
        self, minimal_scenario, empty_index
    ) -> None:
        raw = minimal_scenario(
            profiles=["malformed-media"],
            timeline=[
                {
                    "id": "e_sc",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "a.mkv",
                    "temp_path": "a.mkv.copying",
                    "duration": "5s",
                },
                {
                    "id": "corrupt_header_001",
                    "at": "2s",
                    "action": "corrupt_container_header",
                    "target": "a",
                },
            ],
        )
        collector = IssueCollector()

        rule_timeline_lifecycle(raw, empty_index, collector)

        issues = [i for i in collector.issues if i.code == E_LIFECYCLE_INVALID]
        assert any(
            "corrupt_container_header" in i.message and "pending slow_copy" in i.message
            for i in issues
        )


class TestInterceptorLifecycle:
    """Interceptor actions require a placed target outside pending slow_copy."""

    @staticmethod
    def _slow_copy_start() -> dict[str, object]:
        return {
            "id": "e_sc",
            "at": "1s",
            "action": "slow_copy_start",
            "target": "a",
            "to": "a.mkv",
            "temp_path": "a.mkv.copying",
            "duration": "5s",
        }

    @staticmethod
    def _interceptor_event(action: str, **fields: object) -> dict[str, object]:
        return {
            "id": f"{action}_001",
            "at": "2s",
            "action": action,
            "target": "a",
            **fields,
        }

    @pytest.mark.parametrize(
        ("action", "fields"),
        [
            ("truncate_file", {"keep_bytes": 64}),
            (
                "corrupt_packet_range",
                {"stream": "video", "packet_start": 0, "packet_count": 1},
            ),
            ("write_invalid_duration_metadata", {"value": "not-a-duration"}),
            ("touch_mtime", {"offset": "2s"}),
            ("wrong_oracle_hash", {}),
        ],
    )
    def test_interceptor_after_delete_emits_lifecycle_invalid(
        self, minimal_scenario, empty_index, action, fields
    ) -> None:
        raw = minimal_scenario(
            timeline=[
                {"id": "ev_del", "at": "0s", "action": "delete_file", "target": "a"},
                self._interceptor_event(action, **fields),
            ],
        )
        collector = IssueCollector()

        rule_timeline_lifecycle(raw, empty_index, collector)

        issues = [i for i in collector.issues if i.code == E_LIFECYCLE_INVALID]
        assert any(action in i.message and "unplaced" in i.message for i in issues)

    @pytest.mark.parametrize(
        ("action", "fields"),
        [
            ("truncate_file", {"keep_bytes": 64}),
            (
                "corrupt_packet_range",
                {"stream": "video", "packet_start": 0, "packet_count": 1},
            ),
            ("write_invalid_duration_metadata", {"value": "not-a-duration"}),
            ("touch_mtime", {"offset": "2s"}),
            ("wrong_oracle_hash", {}),
        ],
    )
    def test_interceptor_during_slow_copy_emits_lifecycle_invalid(
        self, minimal_scenario, empty_index, action, fields
    ) -> None:
        raw = minimal_scenario(
            timeline=[
                self._slow_copy_start(),
                self._interceptor_event(action, **fields),
            ],
        )
        collector = IssueCollector()

        rule_timeline_lifecycle(raw, empty_index, collector)

        issues = [i for i in collector.issues if i.code == E_LIFECYCLE_INVALID]
        assert any(action in i.message and "pending slow_copy" in i.message for i in issues)
