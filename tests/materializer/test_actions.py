"""Tests for materializer action-set ownership."""

from __future__ import annotations

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.actions import (
    _CORRUPTION_ACTIONS,
    _FILESYSTEM_ARTIFACT_ACTIONS,
    _HIERARCHY_ACTIONS,
    _MEDIA_ACTIONS,
    _ORACLE_HASH_ACTIONS,
    _STDLIB_ACTIONS,
    PODCAST_ACTIONS,
    SUPPORTED_S6_ACTIONS,
    SUPPORTED_S7_ACTIONS,
    SUPPORTED_S10_ACTIONS,
)
from chaos_librarian.materializer.phase_b.filesystem import supports_filesystem_action


def test_supported_s6_actions_match_sprint_6_materializer_surface() -> None:
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
        == SUPPORTED_S6_ACTIONS
    )


def test_supported_s7_actions_partition_stdlib_and_media_actions() -> None:
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
        == _MEDIA_ACTIONS
    )
    assert (SUPPORTED_S6_ACTIONS - {TimelineActionName.CREATE_SIDECAR}) | frozenset(
        {TimelineActionName.REMOVE_SIDECAR}
    ) == _STDLIB_ACTIONS
    assert SUPPORTED_S7_ACTIONS == _STDLIB_ACTIONS | _MEDIA_ACTIONS


def test_supported_s10_actions_includes_corruption_actions() -> None:
    assert (
        frozenset(
            {
                TimelineActionName.CORRUPT_CONTAINER_HEADER,
                TimelineActionName.TRUNCATE_FILE,
                TimelineActionName.CORRUPT_PACKET_RANGE,
                TimelineActionName.WRITE_INVALID_DURATION_METADATA,
            }
        )
        == _CORRUPTION_ACTIONS
    )
    assert frozenset({TimelineActionName.TOUCH_MTIME}) == _FILESYSTEM_ARTIFACT_ACTIONS
    assert frozenset({TimelineActionName.WRONG_ORACLE_HASH}) == _ORACLE_HASH_ACTIONS
    assert SUPPORTED_S10_ACTIONS == (
        _STDLIB_ACTIONS
        | _MEDIA_ACTIONS
        | _CORRUPTION_ACTIONS
        | _ORACLE_HASH_ACTIONS
        | _FILESYSTEM_ARTIFACT_ACTIONS
        | _HIERARCHY_ACTIONS
        | PODCAST_ACTIONS
    )


def test_supported_s10_actions_include_hierarchy_filesystem_actions() -> None:
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
    assert expected == _HIERARCHY_ACTIONS
    assert expected <= SUPPORTED_S10_ACTIONS
    assert all(supports_filesystem_action(action) for action in _HIERARCHY_ACTIONS)


def test_mark_episode_stale_is_supported_without_filesystem_effect() -> None:
    assert frozenset({TimelineActionName.MARK_EPISODE_STALE}) == PODCAST_ACTIONS
    assert TimelineActionName.MARK_EPISODE_STALE in SUPPORTED_S10_ACTIONS
    # No on-disk change: the file lingers, so there is no filesystem handler.
    assert not supports_filesystem_action(TimelineActionName.MARK_EPISODE_STALE)
