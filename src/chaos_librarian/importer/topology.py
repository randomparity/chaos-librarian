"""Map probed input files onto the scenario hierarchy (issue #105).

Conventions (spec): a video directly under a ``Season NN`` directory is a
series episode (series name = grandparent directory); any other video is a
movie — multiple videos in one directory become variants of one movie;
audio under ``<Artist>/<Album>[/Disc NN]/`` becomes artist/album/disc/track.
Sidecars attach to the nearest same-directory stem-matching video, deduped
per (video, kind, language). Podcasts are not detected. Every name-derived
surface passes through one conservative sanitizer so downstream path
rendering never sees control characters or separators.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from chaos_librarian.importer.probe_input import ProbedInput
from chaos_librarian.importer.scan import (
    SUBTITLE_EXTENSIONS_BY_SUFFIX,
    ScannedFile,
    SkipRecord,
)

__all__ = ["ImportedWork", "attach_sidecars", "build_topology", "sanitize"]

_SEASON_RE = re.compile(r"season[ _-]?(\d{1,2})", re.IGNORECASE)
_SXXEYY_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{1,2})")
_LANGUAGE_RE = re.compile(r"\.([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)?)$")
_CODEC_WORDS = frozenset({"srt", "ass", "ssa"})
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9 _'\-]+")
_WHITESPACE_RE = re.compile(r"\s+")

_POSTER_FORMAT_BY_SUFFIX = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}


def sanitize(name: str) -> str:
    """Conservative display-name sanitizer.

    Strips everything outside ``[A-Za-z0-9 _'-]``, collapses whitespace, and
    caps length at 64. Deliberately NOT ``path_rendering.clean_display_component``
    — that helper validates (raises) instead of sanitizing; this guarantees
    its precondition holds downstream.
    """
    cleaned = _WHITESPACE_RE.sub(" ", _SANITIZE_RE.sub("", name)).strip()
    return cleaned[:64].strip()


def _slug(name: str) -> str:
    return sanitize(name).lower().replace(" ", "-")


def _display_name(name: str, allocated_id: str, *, prefix: str = "") -> str:
    title = sanitize(name)
    return title if allocated_id == f"{prefix}{_slug(name)}" else f"{title} {allocated_id}"


def _language_for(sidecar: ScannedFile) -> str:
    match = _LANGUAGE_RE.search(sidecar.path.stem.lower())
    if match and match.group(1) not in _CODEC_WORDS:
        return match.group(1)
    return "en"


def _container_of(path: Path) -> str:
    return path.suffix.lstrip(".").lower()


@dataclass
class _IdAllocator:
    """Deterministic slug ids with ``-<n>`` disambiguators in sorted order."""

    slugs: set[str] = field(default_factory=set)

    def unique_id(self, slug: str) -> str:
        candidate = slug
        count = 0
        while candidate in self.slugs:
            count += 1
            candidate = f"{slug}-{count}"
        self.slugs.add(candidate)
        return candidate


@dataclass
class ImportedWork:
    """One emitted movie/series/artist with its assets and sidecar events."""

    kind: str  # "movie" | "series" | "artist"
    id: str
    payload: dict[str, object]
    asset_payloads: list[dict[str, object]] = field(default_factory=list)
    sidecar_events: list[dict[str, object]] = field(default_factory=list)
    # asset id -> original scanned path; sidecar attachment looks this up.
    asset_sources: dict[str, Path] = field(default_factory=dict)
    event_counters: dict[str, int] = field(default_factory=dict)
    ids: _IdAllocator = field(default_factory=_IdAllocator, repr=False)

    def next_event_id(self, asset_id: str) -> str:
        n = self.event_counters.get(asset_id, 0) + 1
        self.event_counters[asset_id] = n
        return self.ids.unique_id(f"sidecar-{asset_id}-{n}")


def build_topology(  # noqa: PLR0912, PLR0915 — one branch per spec convention; splitting would scatter the shared allocator/registry state across helpers without reducing risk.
    probed: list[ProbedInput],
    sidecars: list[ScannedFile],
    root: Path,
) -> tuple[list[ImportedWork], list[SkipRecord]]:
    """Classify probed files into works; attach sidecars deterministically.

    Single responsibility: turn flat probe results into hierarchy works plus
    an observable skip list. Long by nature — every branch is one documented
    convention from the spec.
    """
    skips: list[SkipRecord] = []
    works: list[ImportedWork] = []
    allocator = _IdAllocator(slugs={"main"})
    imported_video_paths: set[Path] = set()

    videos = [item for item in probed if item.scanned.kind == "video"]
    audios = [item for item in probed if item.scanned.kind == "audio"]

    def next_asset_id(digest: str) -> str:
        return allocator.unique_id(f"imp-{digest[:12]}")

    def make_asset(item: ProbedInput, asset_id: str) -> dict[str, object]:
        # emit.py rewrites __BUNDLE__#<sha256> to the staged bundle-relative
        # path; carrying the digest makes the rewrite content-addressed.
        return {
            "id": asset_id,
            "role": "main",
            "container": _container_of(item.scanned.path),
            "duration_seconds": item.probed.duration_seconds,
            "import_source": {"path": f"__BUNDLE__#{item.sha256}"},
        }

    # --- series episodes ----------------------------------------------------
    series_works: dict[str, ImportedWork] = {}
    seasons_by_series: dict[str, dict[int, list[dict[str, object]]]] = {}
    episode_seen: set[tuple[str, int, int]] = set()
    series_paths: set[Path] = set()
    season_handled: set[Path] = set()
    series_ids: dict[Path, str] = {}

    for item in videos:
        season_dir = item.scanned.path.parent
        season_match = _SEASON_RE.fullmatch(season_dir.name)
        if season_match is None:
            continue
        season_handled.add(item.scanned.path)
        grandparent = season_dir.parent
        if grandparent.resolve() == root.resolve() or not sanitize(grandparent.name):
            skips.append(SkipRecord(path=item.scanned.path, reason="topology:no_anchor"))
            continue
        episode_match = _SXXEYY_RE.search(item.scanned.path.stem)
        if episode_match is None:
            skips.append(SkipRecord(path=item.scanned.path, reason="topology:no_anchor"))
            continue
        season_number = int(season_match.group(1))
        episode_number = int(episode_match.group(2))
        if grandparent.resolve() not in series_ids:
            series_ids[grandparent.resolve()] = allocator.unique_id(
                _slug(sanitize(grandparent.name))
            )
        work_id = series_ids[grandparent.resolve()]
        if (work_id, season_number, episode_number) in episode_seen:
            skips.append(SkipRecord(path=item.scanned.path, reason="topology:duplicate_episode"))
            continue
        episode_seen.add((work_id, season_number, episode_number))

        asset_id = next_asset_id(item.sha256)
        stem_title = (
            sanitize(_SXXEYY_RE.sub("", item.scanned.path.stem).strip(" -_"))
            or f"Episode {episode_number:02d}"
        )
        work = series_works.get(work_id)
        if work is None:
            work = ImportedWork(
                kind="series",
                ids=allocator,
                id=work_id,
                payload={
                    "id": work_id,
                    "title": _display_name(grandparent.name, work_id),
                    "layout": "season_folders",
                    "episode_naming": "sxxexx_title",
                    "seasons": [],
                },
            )
            series_works[work_id] = work
            seasons_by_series[work_id] = {}
        variant: dict[str, object] = {
            "id": allocator.unique_id(f"{work_id}-s{season_number:02d}e{episode_number:02d}v"),
            "label": "default",
            "bundle": {
                "id": allocator.unique_id(f"{asset_id}-b"),
                "assets": [make_asset(item, asset_id)],
            },
        }
        episode: dict[str, object] = {
            "id": allocator.unique_id(f"{work_id}-s{season_number:02d}e{episode_number:02d}"),
            "episode_number": episode_number,
            "title": stem_title,
            "variants": [variant],
        }
        seasons_by_series[work_id].setdefault(season_number, []).append(episode)
        assets = variant["bundle"]["assets"]
        assert isinstance(assets, list)
        assert len(assets) == 1
        work.asset_payloads.append(assets[0])
        work.asset_sources[asset_id] = item.scanned.path
        series_paths.add(item.scanned.path)

    for work_id, seasons in seasons_by_series.items():
        payload_seasons = [
            {
                "id": allocator.unique_id(f"{work_id}-s{number:02d}"),
                "season_number": number,
                "title": f"Season {number:02d}",
                "episodes": episodes,
            }
            for number, episodes in sorted(seasons.items())
        ]
        series_works[work_id].payload["seasons"] = payload_seasons
    works.extend(series_works.values())

    # --- movies -------------------------------------------------------------
    movie_groups: dict[Path, list[ProbedInput]] = {}
    for item in videos:
        if item.scanned.path in series_paths or item.scanned.path in season_handled:
            continue
        key = item.scanned.path.parent.resolve()
        movie_groups.setdefault(key, []).append(item)

    for dir_path, items in sorted(movie_groups.items()):
        ordered = sorted(items, key=lambda i: i.scanned.path)
        at_root = dir_path == root.resolve()
        title_source = ordered[0].scanned.path.stem if at_root else dir_path.name
        title = sanitize(title_source)
        if not title:
            for item in ordered:
                skips.append(SkipRecord(path=item.scanned.path, reason="topology:no_anchor"))
            continue
        work_id = allocator.unique_id(_slug(title))
        work = ImportedWork(
            kind="movie",
            ids=allocator,
            id=work_id,
            payload={
                "id": work_id,
                "title": _display_name(title, work_id),
                "layout": "movie_folder" if not at_root else "movie_flat",
                "variants": [],
            },
        )
        variants = work.payload["variants"]
        assert isinstance(variants, list)
        typed_variants = cast("list[dict[str, object]]", variants)
        for index, item in enumerate(ordered):
            asset_id = next_asset_id(item.sha256)
            variant: dict[str, object] = {
                "id": allocator.unique_id(f"{work_id}v{index + 1}"),
                "label": f"v{index + 1}",
                "bundle": {
                    "id": allocator.unique_id(f"{asset_id}-b"),
                    "assets": [make_asset(item, asset_id)],
                },
            }
            typed_variants.append(variant)
            assets = variant["bundle"]["assets"]
            assert isinstance(assets, list)
            assert len(assets) == 1
            work.asset_payloads.append(assets[0])
            work.asset_sources[asset_id] = item.scanned.path
            imported_video_paths.add(item.scanned.path)
        works.append(work)

    artist_works: dict[Path, ImportedWork] = {}
    album_payloads: dict[Path, dict[str, object]] = {}
    disc_payloads: dict[tuple[Path, int], dict[str, object]] = {}
    for item in audios:
        track_dir = item.scanned.path.parent
        disc_match = re.fullmatch(r"disc[ _-]?(\d{1,2})", track_dir.name, re.IGNORECASE)
        album_dir = track_dir.parent if disc_match else track_dir
        artist_dir = album_dir.parent
        if (
            artist_dir == root
            or root not in artist_dir.parents
            or not sanitize(artist_dir.name)
            or not sanitize(album_dir.name)
        ):
            skips.append(SkipRecord(path=item.scanned.path, reason="topology:no_anchor"))
            continue
        work = artist_works.get(artist_dir)
        if work is None:
            work_id = allocator.unique_id(_slug(artist_dir.name))
            work = ImportedWork(
                kind="artist",
                ids=allocator,
                id=work_id,
                payload={
                    "id": work_id,
                    "name": _display_name(artist_dir.name, work_id),
                    "layout": "artist_album_disc",
                    "track_naming": "track_number_title",
                    "albums": [],
                },
            )
            artist_works[artist_dir] = work
            works.append(work)
        album: dict[str, object] | None = album_payloads.get(album_dir)
        if album is None:
            album_id = allocator.unique_id(f"{work.id}-{_slug(album_dir.name)}")
            album = {
                "id": album_id,
                "title": _display_name(album_dir.name, album_id, prefix=f"{work.id}-"),
                "discs": [],
            }
            album_payloads[album_dir] = album
            cast("list[dict[str, object]]", work.payload["albums"]).append(album)
        disc_number = int(disc_match.group(1)) if disc_match else 1
        disc: dict[str, object] | None = disc_payloads.get((album_dir, disc_number))
        if disc is None:
            disc = {
                "id": allocator.unique_id(f"{album['id']}-d{disc_number}"),
                "disc_number": disc_number,
                "tracks": [],
            }
            disc_payloads[(album_dir, disc_number)] = disc
            cast("list[dict[str, object]]", album["discs"]).append(disc)
        tracks = cast("list[dict[str, object]]", disc["tracks"])
        track_number = len(tracks) + 1
        track_id = allocator.unique_id(f"{disc['id']}-t{track_number}")
        asset_id = next_asset_id(item.sha256)
        asset = make_asset(item, asset_id)
        tracks.append(
            {
                "id": track_id,
                "track_number": track_number,
                "title": sanitize(item.scanned.path.stem) or f"Track {track_number}",
                "variants": [
                    {
                        "id": allocator.unique_id(f"{track_id}v"),
                        "label": "default",
                        "bundle": {"id": allocator.unique_id(f"{asset_id}-b"), "assets": [asset]},
                    }
                ],
            }
        )
        work.asset_payloads.append(asset)
        work.asset_sources[asset_id] = item.scanned.path

    attach_sidecars(works, sidecars, skips)
    del imported_video_paths
    return works, skips


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", newline="")


def attach_sidecars(
    works: list[ImportedWork],
    sidecars: list[ScannedFile],
    skips: list[SkipRecord],
) -> None:
    """Attach sidecars to stem-matching videos; dedup per (video, kind, language).

    Ambiguous stems attach to the lexicographically first matching video;
    later duplicates skip as ``sidecar_duplicate``; an unmatched sidecar
    skips as ``orphaned_sidecar``.
    """
    entries: list[tuple[Path, str, str, ImportedWork]] = []
    for work in works:
        if work.kind == "artist":
            continue
        for asset_id, source_path in sorted(work.asset_sources.items()):
            entries.append((source_path.parent.resolve(), source_path.stem.lower(), asset_id, work))

    attached: set[tuple[str, str, str]] = set()

    for sidecar in sorted(sidecars, key=lambda s: s.path):
        parent = sidecar.path.parent.resolve()
        if sidecar.kind == "poster":
            # Posters attach per directory (spec): the directory's
            # lexicographically first imported asset, no stem match.
            dir_entries = sorted((e for e in entries if e[0] == parent), key=lambda e: e[1])
            if not dir_entries:
                skips.append(SkipRecord(path=sidecar.path, reason="orphaned_sidecar"))
                continue
            _, _, asset_id, work = dir_entries[0]
            dedup_key = (asset_id, "poster", sidecar.path.stem.lower())
            if dedup_key in attached:
                skips.append(SkipRecord(path=sidecar.path, reason="sidecar_duplicate"))
                continue
            attached.add(dedup_key)
            ext = sidecar.path.suffix.lower().lstrip(".")
            _append_event(
                work,
                {
                    "id": work.next_event_id(asset_id),
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": asset_id,
                    "to": f"{sanitize(sidecar.path.stem)}.{ext}",
                    "kind": "poster",
                    "media_type": "image",
                    "image_format": _POSTER_FORMAT_BY_SUFFIX[f".{ext}"],
                },
            )
            continue
        stem_lower = sidecar.path.stem.lower()
        candidates = sorted(
            (
                entry
                for entry in entries
                if entry[0] == parent
                and (stem_lower == entry[1] or stem_lower.startswith(entry[1] + "."))
            ),
            key=lambda entry: entry[1],
        )
        if not candidates:
            skips.append(SkipRecord(path=sidecar.path, reason="orphaned_sidecar"))
            continue
        _, matched_stem, asset_id, work = candidates[0]

        if sidecar.kind == "subtitle":
            codec = SUBTITLE_EXTENSIONS_BY_SUFFIX[sidecar.path.suffix.lower()]
            language = _language_for(sidecar)
            dedup_key = (asset_id, "subtitle", language)
            if dedup_key in attached:
                skips.append(SkipRecord(path=sidecar.path, reason="sidecar_duplicate"))
                continue
            attached.add(dedup_key)
            _append_event(
                work,
                {
                    "id": work.next_event_id(asset_id),
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": asset_id,
                    "to": f"{sanitize(matched_stem)}.{language}.{codec}",
                    "kind": "subtitle",
                    "codec": codec,
                    "language": language,
                    "body": _read_text(sidecar.path),
                },
            )
        elif sidecar.kind == "nfo":
            dedup_key = (asset_id, "nfo", "")
            if dedup_key in attached:
                skips.append(SkipRecord(path=sidecar.path, reason="sidecar_duplicate"))
                continue
            attached.add(dedup_key)
            _append_event(
                work,
                {
                    "id": work.next_event_id(asset_id),
                    "at": "0s",
                    "action": "create_sidecar",
                    "target": asset_id,
                    "to": f"{sanitize(matched_stem)}.nfo",
                    "kind": "nfo",
                    "body": _read_text(sidecar.path),
                },
            )


def _append_event(work: ImportedWork, event: dict[str, object]) -> None:
    work.sidecar_events.append(event)
