"""Shared domain enums for public contracts."""

from __future__ import annotations

import enum


class ParentKind(enum.StrEnum):
    """Playable/listenable parent kinds for variants and assets."""

    MOVIE = "movie"
    EPISODE = "episode"
    TRACK = "track"
