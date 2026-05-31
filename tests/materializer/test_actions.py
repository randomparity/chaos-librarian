"""Tests for materializer action-set ownership."""

from __future__ import annotations

from chaos_librarian.contract.materialization import CORRUPTION_TIMELINE_ACTIONS
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.actions import (
    BASE_FILESYSTEM_ACTIONS,
    FILESYSTEM_ARTIFACT_ACTIONS,
    HIERARCHY_PHASE_B_ACTIONS,
    MATERIALIZE_SUPPORTED_ACTIONS,
    MEDIA_PHASE_B_ACTIONS,
    ORACLE_HASH_PHASE_B_ACTIONS,
    PODCAST_ACTIONS,
    STDLIB_PHASE_B_ACTIONS,
)
from chaos_librarian.materializer.phase_b.filesystem import supports_filesystem_action


def test_base_filesystem_actions_match_materializer_file_surface() -> None:
    assert (
        frozenset(
            {
                TimelineActionName.MOVE_ASSET,
                TimelineActionName.RENAME_FILE,
                TimelineActionName.DELETE_FILE,
                TimelineActionName.ADD_FILE,
                TimelineActionName.CREATE_SIDECAR,
                TimelineActionName.SLOW_COPY_START,
                TimelineActionName.SLOW_COPY_COMMIT,
                TimelineActionName.ARCHIVE_FILE,
                TimelineActionName.MOVE_BETWEEN_ROOTS,
            }
        )
        == BASE_FILESYSTEM_ACTIONS
    )


def test_core_phase_b_actions_partition_stdlib_and_media_handlers() -> None:
    assert (
        frozenset(
            {
                TimelineActionName.REENCODE_VIDEO,
                TimelineActionName.REENCODE_AUDIO,
                TimelineActionName.REMUX_CONTAINER,
                TimelineActionName.EDIT_METADATA,
                TimelineActionName.EMBED_SUBTITLE,
                TimelineActionName.EXTRACT_SUBTITLE,
                TimelineActionName.UPDATE_SIDECAR,
                TimelineActionName.CREATE_SIDECAR,
            }
        )
        == MEDIA_PHASE_B_ACTIONS
    )
    assert (BASE_FILESYSTEM_ACTIONS - {TimelineActionName.CREATE_SIDECAR}) | frozenset(
        {TimelineActionName.REMOVE_SIDECAR}
    ) == STDLIB_PHASE_B_ACTIONS
    assert STDLIB_PHASE_B_ACTIONS | MEDIA_PHASE_B_ACTIONS <= MATERIALIZE_SUPPORTED_ACTIONS


def test_materialize_supported_actions_include_corruption_actions() -> None:
    assert (
        frozenset(
            {
                TimelineActionName.CORRUPT_CONTAINER_HEADER,
                TimelineActionName.TRUNCATE_FILE,
                TimelineActionName.CORRUPT_PACKET_RANGE,
                TimelineActionName.WRITE_INVALID_DURATION_METADATA,
                TimelineActionName.CORRUPT_TAGS,
            }
        )
        == CORRUPTION_TIMELINE_ACTIONS
    )
    assert frozenset({TimelineActionName.TOUCH_MTIME}) == FILESYSTEM_ARTIFACT_ACTIONS
    assert frozenset({TimelineActionName.WRONG_ORACLE_HASH}) == ORACLE_HASH_PHASE_B_ACTIONS
    assert MATERIALIZE_SUPPORTED_ACTIONS == (
        STDLIB_PHASE_B_ACTIONS
        | MEDIA_PHASE_B_ACTIONS
        | CORRUPTION_TIMELINE_ACTIONS
        | ORACLE_HASH_PHASE_B_ACTIONS
        | FILESYSTEM_ARTIFACT_ACTIONS
        | HIERARCHY_PHASE_B_ACTIONS
        | PODCAST_ACTIONS
    )


def test_materialize_supported_actions_include_hierarchy_filesystem_actions() -> None:
    expected = frozenset(
        {
            TimelineActionName.RENUMBER_EPISODE,
            TimelineActionName.MOVE_EPISODE_TO_SEASON,
            TimelineActionName.RENAME_SEASON,
            TimelineActionName.RENUMBER_DISC,
            TimelineActionName.MOVE_TRACK_TO_DISC,
            TimelineActionName.SWAP_EPISODE_NUMBERS,
            TimelineActionName.SWAP_DISC_NUMBERS,
            TimelineActionName.SWAP_TRACK_NUMBERS,
            TimelineActionName.REPUBLISH_EPISODE,
        }
    )
    assert expected == HIERARCHY_PHASE_B_ACTIONS
    assert expected <= MATERIALIZE_SUPPORTED_ACTIONS
    assert all(supports_filesystem_action(action) for action in HIERARCHY_PHASE_B_ACTIONS)


def test_mark_episode_stale_is_supported_without_filesystem_effect() -> None:
    assert frozenset({TimelineActionName.MARK_EPISODE_STALE}) == PODCAST_ACTIONS
    assert TimelineActionName.MARK_EPISODE_STALE in MATERIALIZE_SUPPORTED_ACTIONS
    # No on-disk change: the file lingers, so there is no filesystem handler.
    assert not supports_filesystem_action(TimelineActionName.MARK_EPISODE_STALE)
