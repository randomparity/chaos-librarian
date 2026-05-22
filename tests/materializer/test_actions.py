"""Tests for materializer action-set ownership."""

from __future__ import annotations

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.actions import (
    _MEDIA_ACTIONS,
    _STDLIB_ACTIONS,
    SUPPORTED_S6_ACTIONS,
    SUPPORTED_S7_ACTIONS,
)


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
