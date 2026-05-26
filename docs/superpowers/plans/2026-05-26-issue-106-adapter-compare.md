# Issue 106 Adapter Compare Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish adapter/compare support for schema v12 hierarchy fixtures and observed-state v2 topology.

**Architecture:** Keep adapter inputs normalized: fixture loading reads domain report families, observed-state uses normalized domain rows, and matching compares deterministic evidence indexes. Replace the old generic work-like topology fallback with domain-specific movie, episode, and track keys while keeping existing path/hash precedence and `D_TOPOLOGY_MISMATCH` output.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, Typer CLI tests, ruff, ty.

---

## Context

The parent plan is `docs/superpowers/plans/2026-05-26-issue-106-media-hierarchies.md`.
Contract, validation, engine/reports, and materializer slices have already
landed. Adapter code already imports the new domain report and observed-state
models, but the adapter test surface still has gaps:

- `tests/adapter/test_observed.py` still uses `schema_version: 1`.
- `tests/cli/test_compare.py::test_compare_missing_sentinel_exits_seven`
  currently catches the wrong sentinel exception type.
- `tests/cli/test_compare.py::test_compare_identity_history_missing_evidence_exits_six`
  currently uses a synthetic static fixture for `identity-move-rename.yaml`,
  so no identity history is expected.
- `src/chaos_librarian/adapter/index.py` still builds topology fallback keys
  from `parent_kind|parent_title|variant_label|member_count`, which is too
  weak for TV/music hierarchies.

## Files

- Modify: `src/chaos_librarian/adapter/fixture.py`
- Modify: `src/chaos_librarian/adapter/index.py`
- Modify: `src/chaos_librarian/adapter/compare.py`
- Modify: `src/chaos_librarian/cli/commands/compare.py`
- Modify: `tests/support/adapter.py`
- Modify: `tests/adapter/test_fixture.py`
- Modify: `tests/adapter/test_matching.py`
- Modify: `tests/adapter/test_compare_final_state.py`
- Modify: `tests/adapter/test_observed.py`
- Modify: `tests/cli/test_compare.py`
- Modify: `tests/contract/test_observed_state.py`

No contract model or schema changes are expected in this child plan. If a
contract field is missing, stop and report `NEEDS_CONTEXT`; do not add new
contract fields from the adapter slice.

## Task 1: Repair Adapter v2 Baseline

**Files:**
- Modify: `src/chaos_librarian/cli/commands/compare.py`
- Modify: `tests/adapter/test_observed.py`
- Modify: `tests/support/adapter.py`

- [ ] **Step 1: Verify current RED baseline**

Run:

```bash
uv run pytest tests/adapter/test_observed.py tests/cli/test_compare.py::test_compare_identity_history_missing_evidence_exits_six tests/cli/test_compare.py::test_compare_missing_sentinel_exits_seven -q --no-cov
```

Expected before this task:

```text
FAILED tests/adapter/test_observed.py::test_load_observed_state_reads_valid_json
FAILED tests/cli/test_compare.py::test_compare_identity_history_missing_evidence_exits_six
FAILED tests/cli/test_compare.py::test_compare_missing_sentinel_exits_seven
```

- [ ] **Step 2: Update observed loader fixture payload to v2**

In `tests/adapter/test_observed.py`, change the helper payload header from:

```json
{
  "schema_version": 1,
  "consumer": {"name": "voom-v2", "version": "0.9.0"},
  "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
  "observed_at": "2026-05-22T12:00:00Z",
  "assets": [
    {
      "observed_ref": "obs-asset-1",
      "current_path": "movies/Synthetic.mkv"
    }
  ]
}
```

to:

```json
{
  "schema_version": 2,
  "consumer": {"name": "voom-v2", "version": "0.9.0"},
  "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
  "observed_at": "2026-05-22T12:00:00Z",
  "assets": [
    {
      "observed_ref": "obs-asset-1",
      "current_path": "movies/Synthetic.mkv"
    }
  ]
}
```

Keep `test_load_observed_state_rejects_schema_invalid_json()` as an invalid
payload test; it may continue using an intentionally incomplete payload.

- [ ] **Step 3: Make compare catch adapter sentinel errors**

In `src/chaos_librarian/cli/commands/compare.py`, replace the engine sentinel
import with the adapter fixture sentinel type:

```python
from chaos_librarian.adapter.fixture import SentinelInvalidError
```

Remove:

```python
from chaos_librarian.engine import SentinelInvalidError
```

The existing `except SentinelInvalidError` block should remain unchanged.

- [ ] **Step 4: Stop synthesizing the identity-move fixture**

In `tests/support/adapter.py`, change:

```python
_SYNTHETIC_SCENARIOS = frozenset({"identity-move-rename.yaml", "static-library.yaml"})
```

to:

```python
_SYNTHETIC_SCENARIOS = frozenset({"static-library.yaml"})
```

This makes compare identity-history tests use the real v12
`tests/fixtures/scenarios/identity-move-rename.yaml` fixture, whose journal has
move/rename path history.

- [ ] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/adapter/test_observed.py tests/cli/test_compare.py::test_compare_identity_history_missing_evidence_exits_six tests/cli/test_compare.py::test_compare_missing_sentinel_exits_seven -q --no-cov
uv run pytest tests/adapter tests/cli/test_compare.py -q --no-cov
uv run ruff check src/chaos_librarian/cli/commands/compare.py tests/adapter/test_observed.py tests/support/adapter.py tests/cli/test_compare.py
uv run ruff format --check src/chaos_librarian/cli/commands/compare.py tests/adapter/test_observed.py tests/support/adapter.py tests/cli/test_compare.py
uv run ty check src tests
git diff --check
git add src/chaos_librarian/cli/commands/compare.py tests/adapter/test_observed.py tests/support/adapter.py
git commit -m "fix: align adapter compare with observed v2"
```

## Task 2: Pin Domain Report Loading

**Files:**
- Modify: `tests/adapter/test_fixture.py`

- [ ] **Step 1: Add failing or confirming report-directory coverage**

In `tests/adapter/test_fixture.py`, replace the three one-off missing report
tests for movies/variants/bundles with one parameterized test that covers every
required report family:

```python
@pytest.mark.parametrize(
    "directory_name",
    [
        "assets",
        "movies",
        "series",
        "seasons",
        "episodes",
        "artists",
        "albums",
        "discs",
        "tracks",
        "variants",
        "bundles",
    ],
)
def test_load_fixture_rejects_missing_report_family(
    tmp_path: Path,
    directory_name: str,
) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    reports_dir = run_dir / "reports" / directory_name
    reports = sorted(reports_dir.glob("*.json"))
    for report in reports:
        report.unlink()
    reports_dir.rmdir()

    _assert_fixture_invalid(run_dir)
```

Then add an explicit old report directory rejection:

```python
def test_load_fixture_rejects_old_work_report_directory(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    works_dir = run_dir / "reports" / "works"
    works_dir.mkdir()
    (works_dir / "work-a.json").write_text("{}")

    _assert_fixture_invalid(run_dir)
```

- [ ] **Step 2: Run the tests**

Run:

```bash
uv run pytest tests/adapter/test_fixture.py -q --no-cov
```

Expected: if the current loader already rejects these cases, the new tests pass
without production changes. If `reports/works` is silently ignored, update
`_load_present_reports()` in `src/chaos_librarian/adapter/fixture.py` to reject
unknown directories:

```python
present_names = {path.name for path in reports_dir.iterdir() if path.is_dir()}
expected_names = set(_REPORT_DIR_NAMES)
if present_names != expected_names:
    _fixture_invalid(
        "reports directory set does not match required report families",
        path=reports_dir,
        details={
            "missing": sorted(expected_names - present_names),
            "extra": sorted(present_names - expected_names),
        },
    )
```

Place this check before the per-family `is_dir()` loop.

- [ ] **Step 3: Verify and commit**

Run:

```bash
uv run pytest tests/adapter/test_fixture.py -q --no-cov
uv run ruff check src/chaos_librarian/adapter/fixture.py tests/adapter/test_fixture.py
uv run ruff format --check src/chaos_librarian/adapter/fixture.py tests/adapter/test_fixture.py
uv run ty check src tests
git diff --check
git add src/chaos_librarian/adapter/fixture.py tests/adapter/test_fixture.py
git commit -m "test: enforce adapter domain report families"
```

If `src/chaos_librarian/adapter/fixture.py` did not change, omit it from
`git add`.

## Task 3: Replace Generic Topology Keys With Domain Keys

**Files:**
- Modify: `src/chaos_librarian/adapter/index.py`
- Modify: `src/chaos_librarian/adapter/compare.py`
- Modify: `tests/adapter/test_matching.py`
- Modify: `tests/adapter/test_compare_final_state.py`

- [ ] **Step 1: Add failing topology-key tests**

In `tests/adapter/test_matching.py`, update `_oracle_topology()` and
`_observed_topology()` to accept optional domain fields:

```python
def _oracle_topology(
    asset_id: str,
    *,
    title: str = "Synthetic",
    label: str,
    parent_kind: ParentKind = ParentKind.MOVIE,
    series_title: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
    episode_title: str | None = None,
    artist_name: str | None = None,
    album_title: str | None = None,
    disc_number: int | None = None,
    track_number: int | None = None,
    track_title: str | None = None,
) -> OracleTopologyView:
    return OracleTopologyView(
        asset_id=asset_id,
        bundle_id=f"oracle-bundle-{asset_id}",
        variant_id=f"oracle-variant-{asset_id}",
        parent_kind=parent_kind,
        parent_id=f"oracle-{parent_kind.value}-{asset_id}",
        movie_title=title if parent_kind is ParentKind.MOVIE else None,
        series_title=series_title,
        season_number=season_number,
        episode_number=episode_number,
        episode_title=episode_title,
        artist_name=artist_name,
        album_title=album_title,
        disc_number=disc_number,
        track_number=track_number,
        track_title=track_title,
        variant_label=label,
        bundle_asset_ids=(asset_id,),
    )
```

Add the same optional fields to `_observed_topology()`, using
`ObservedTopologyView`.

Then update `test_topology_match_records_match_evidence()` to expect the movie
key:

```python
assert result.matches[0].evidence[0].value == "movie:Synthetic|4k|1"
```

Add episode and track matching tests:

```python
def test_topology_match_uses_episode_domain_key() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a"),),
        (_observed_asset("observed-a"),),
        oracle_topology=(
            _oracle_topology(
                "oracle-a",
                label="hd",
                parent_kind=ParentKind.EPISODE,
                series_title="Starline",
                season_number=1,
                episode_number=2,
                episode_title="Pilot",
            ),
        ),
        observed_topology=(
            _observed_topology(
                "observed-a",
                label="hd",
                parent_kind=ParentKind.EPISODE,
                series_title="Starline",
                season_number=1,
                episode_number=2,
                episode_title="Pilot",
            ),
        ),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].evidence[0].value == "episode:Starline|1|2|Pilot|hd"


def test_topology_match_uses_track_domain_key() -> None:
    oracle, observed = _indexes(
        (_oracle_asset("oracle-a"),),
        (_observed_asset("observed-a"),),
        oracle_topology=(
            _oracle_topology(
                "oracle-a",
                label="lossless",
                parent_kind=ParentKind.TRACK,
                artist_name="North Index",
                album_title="Winter Index",
                disc_number=1,
                track_number=3,
                track_title="Opening",
            ),
        ),
        observed_topology=(
            _observed_topology(
                "observed-a",
                label="lossless",
                parent_kind=ParentKind.TRACK,
                artist_name="North Index",
                album_title="Winter Index",
                disc_number=1,
                track_number=3,
                track_title="Opening",
            ),
        ),
    )

    result = match_assets(oracle, observed)

    assert result.matches[0].evidence[0].value == (
        "track:North Index|Winter Index|1|3|Opening|lossless"
    )
```

Run:

```bash
uv run pytest tests/adapter/test_matching.py::test_topology_match_records_match_evidence tests/adapter/test_matching.py::test_topology_match_uses_episode_domain_key tests/adapter/test_matching.py::test_topology_match_uses_track_domain_key -q --no-cov
```

Expected: fail because `OracleTopologyView` / `ObservedTopologyView` do not
yet expose those fields and `topology_key()` still emits the generic key.

- [ ] **Step 2: Extend topology views and key function**

In `src/chaos_librarian/adapter/index.py`, replace `parent_title` on both
topology view dataclasses with domain-specific nullable fields:

```python
@dataclass(frozen=True)
class OracleTopologyView:
    asset_id: str
    bundle_id: str
    variant_id: str
    parent_kind: ParentKind
    parent_id: str
    movie_title: str | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    artist_name: str | None = None
    album_title: str | None = None
    disc_number: int | None = None
    track_number: int | None = None
    track_title: str | None = None
    variant_label: str | None = None
    bundle_asset_ids: tuple[str, ...] = ()
```

Use the same field names on `ObservedTopologyView`, with `observed_ref`,
`bundle_ref`, `variant_ref`, `parent_kind`, and `parent_ref` first.

Replace `topology_key()` with:

```python
def topology_key(
    *,
    parent_kind: ParentKind | None,
    variant_label: str | None,
    bundle_member_count: int,
    movie_title: str | None = None,
    series_title: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
    episode_title: str | None = None,
    artist_name: str | None = None,
    album_title: str | None = None,
    disc_number: int | None = None,
    track_number: int | None = None,
    track_title: str | None = None,
) -> str | None:
    """Return the consumer-neutral domain topology key when enough facts exist."""
    label = variant_label or ""
    if parent_kind is ParentKind.MOVIE:
        if movie_title is None:
            return None
        return f"movie:{movie_title}|{label}|{bundle_member_count}"
    if parent_kind is ParentKind.EPISODE:
        if series_title is None or season_number is None or episode_number is None:
            return None
        return f"episode:{series_title}|{season_number}|{episode_number}|{episode_title or ''}|{label}"
    if parent_kind is ParentKind.TRACK:
        if (
            artist_name is None
            or album_title is None
            or disc_number is None
            or track_number is None
        ):
            return None
        return (
            f"track:{artist_name}|{album_title}|{disc_number}|"
            f"{track_number}|{track_title or ''}|{label}"
        )
    return None
```

Update `OracleIndex.from_views()` and `ObservedIndex.from_views()` to call the
new keyword-only function using the fields from the view.

- [ ] **Step 3: Build oracle domain topology facts from manifest**

In `_oracle_topology()`, replace `_oracle_parent_titles()` with a helper that
returns the domain fields for each variant parent:

```python
def _oracle_domain_fields(
    fixture: OracleFixture,
    parent_kind: ParentKind,
    parent_id: str,
) -> dict[str, object | None]:
    manifest = fixture.initial_manifest
    if parent_kind is ParentKind.MOVIE:
        movie = {movie.id: movie for movie in manifest.movies}[parent_id]
        return {"movie_title": movie.title}
    if parent_kind is ParentKind.EPISODE:
        episode = {episode.id: episode for episode in manifest.episodes}[parent_id]
        season = {season.id: season for season in manifest.seasons}[episode.season_id]
        series = {series.id: series for series in manifest.series}[season.series_id]
        return {
            "series_title": series.title,
            "season_number": season.season_number,
            "episode_number": episode.episode_number,
            "episode_title": episode.title,
        }
    track = {track.id: track for track in manifest.tracks}[parent_id]
    disc = {disc.id: disc for disc in manifest.discs}[track.disc_id]
    album = {album.id: album for album in manifest.albums}[disc.album_id]
    artist = {artist.id: artist for artist in manifest.artists}[album.artist_id]
    return {
        "artist_name": artist.name,
        "album_title": album.title,
        "disc_number": disc.disc_number,
        "track_number": track.track_number,
        "track_title": track.title,
    }
```

Use it while constructing `OracleTopologyView`:

```python
domain_fields = _oracle_domain_fields(fixture, variant.parent_kind, variant.parent_id)
views.append(
    OracleTopologyView(
        asset_id=asset.id,
        bundle_id=bundle.id,
        variant_id=variant.id,
        parent_kind=variant.parent_kind,
        parent_id=variant.parent_id,
        variant_label=variant.label,
        bundle_asset_ids=tuple(sorted(bundle_members[bundle.id])),
        **domain_fields,
    )
)
```

- [ ] **Step 4: Build observed domain topology facts from observed state**

In `_observed_topology()`, replace `_observed_parent_titles()` with
`_observed_domain_fields()`:

```python
def _observed_domain_fields(
    state: ObservedState,
    parent_kind: ParentKind | None,
    parent_ref: str | None,
) -> dict[str, object | None]:
    if parent_kind is None or parent_ref is None:
        return {}
    if parent_kind is ParentKind.MOVIE:
        movie = {movie.observed_ref: movie for movie in state.movies}.get(parent_ref)
        return {"movie_title": movie.title if movie else None}
    if parent_kind is ParentKind.EPISODE:
        episode = {episode.observed_ref: episode for episode in state.episodes}.get(parent_ref)
        if episode is None:
            return {}
        season = {season.observed_ref: season for season in state.seasons}.get(
            episode.season_ref
        )
        series = (
            {series.observed_ref: series for series in state.series}.get(season.series_ref)
            if season is not None
            else None
        )
        return {
            "series_title": series.title if series else None,
            "season_number": season.season_number if season else None,
            "episode_number": episode.episode_number,
            "episode_title": episode.title,
        }
    track = {track.observed_ref: track for track in state.tracks}.get(parent_ref)
    if track is None:
        return {}
    disc = {disc.observed_ref: disc for disc in state.discs}.get(track.disc_ref)
    album = (
        {album.observed_ref: album for album in state.albums}.get(disc.album_ref)
        if disc is not None
        else None
    )
    artist = (
        {artist.observed_ref: artist for artist in state.artists}.get(album.artist_ref)
        if album is not None
        else None
    )
    return {
        "artist_name": artist.name if artist else None,
        "album_title": album.title if album else None,
        "disc_number": disc.disc_number if disc else None,
        "track_number": track.track_number,
        "track_title": track.title,
    }
```

Pass `**domain_fields` into `ObservedTopologyView`.

- [ ] **Step 5: Update compare topology payloads**

In `src/chaos_librarian/adapter/compare.py`, update `_compare_topology()` to
call `topology_key()` with the new fields. Keep
`DivergenceCode.TOPOLOGY_MISMATCH`, but change the payload key from generic
`"topology"` to `"domain_key"`:

```python
expected={
    "parent_kind": oracle_topology.parent_kind.value,
    "domain_key": oracle_key,
},
observed={
    "parent_kind": (
        observed_topology.parent_kind.value
        if observed_topology.parent_kind is not None
        else None
    ),
    "domain_key": observed_key,
},
```

Update `tests/adapter/test_compare_final_state.py` to assert `domain_key`
instead of `topology` in topology mismatch payloads.

- [ ] **Step 6: Verify and commit**

Run:

```bash
uv run pytest tests/adapter/test_matching.py tests/adapter/test_compare_final_state.py -q --no-cov
uv run ruff check src/chaos_librarian/adapter/index.py src/chaos_librarian/adapter/compare.py tests/adapter/test_matching.py tests/adapter/test_compare_final_state.py
uv run ruff format --check src/chaos_librarian/adapter/index.py src/chaos_librarian/adapter/compare.py tests/adapter/test_matching.py tests/adapter/test_compare_final_state.py
uv run ty check src tests
git diff --check
git add src/chaos_librarian/adapter/index.py src/chaos_librarian/adapter/compare.py tests/adapter/test_matching.py tests/adapter/test_compare_final_state.py
git commit -m "feat: compare hierarchy topology keys"
```

## Task 4: Emit Full Observed Domain Rows From Fixtures

**Files:**
- Modify: `tests/support/adapter.py`
- Modify: `tests/adapter/test_compare_final_state.py`

- [ ] **Step 1: Add tests for observed topology export**

In `tests/adapter/test_compare_final_state.py`, add two tests that build an
`OracleFixture` with TV and music manifest rows through
`tests.support.adapter.fixture(parent_kind=...)`. Add these tests first:

```python
def test_observed_from_fixture_emits_episode_domain_rows() -> None:
    fixture = _fixture_for_episode()

    observed = _observed_from_fixture(fixture, include_topology=True)

    assert observed.series[0].title == "Starline"
    assert observed.seasons[0].series_ref == "observed-series-a"
    assert observed.episodes[0].season_ref == "observed-season-a"
    assert observed.variants[0].parent_kind is ParentKind.EPISODE
    assert observed.variants[0].parent_ref == "observed-episode-a"


def test_observed_from_fixture_emits_track_domain_rows() -> None:
    fixture = _fixture_for_track()

    observed = _observed_from_fixture(fixture, include_topology=True)

    assert observed.artists[0].name == "North Index"
    assert observed.albums[0].artist_ref == "observed-artist-a"
    assert observed.discs[0].album_ref == "observed-album-a"
    assert observed.tracks[0].disc_ref == "observed-disc-a"
    assert observed.variants[0].parent_kind is ParentKind.TRACK
    assert observed.variants[0].parent_ref == "observed-track-a"
```

Define `_fixture_for_episode()` and `_fixture_for_track()` in the same test file
by using new helpers from `tests/support/adapter.py` added in the next step.

Run:

```bash
uv run pytest tests/adapter/test_compare_final_state.py::test_observed_from_fixture_emits_episode_domain_rows tests/adapter/test_compare_final_state.py::test_observed_from_fixture_emits_track_domain_rows -q --no-cov
```

Expected: fail because support helpers do not yet build full observed domain
rows.

- [ ] **Step 2: Add support fixture builders**

In `tests/support/adapter.py`, extend `manifest()`, `reports()`, and `fixture()`
with an optional `parent_kind: ParentKind = ParentKind.MOVIE` argument. Keep the
existing default behavior unchanged.

For `ParentKind.EPISODE`, build a manifest with:

```python
series=[ManifestSeries(id="series-a", title="Starline", layout="season_folders", episode_naming="sxxexx_title")]
seasons=[ManifestSeason(id="season-a", series_id="series-a", season_number=1, title="Season 1")]
episodes=[ManifestEpisode(id="episode-a", season_id="season-a", episode_number=1, title="Pilot")]
movies=[]
artists=[]
albums=[]
discs=[]
tracks=[]
variants=[ManifestVariant(id="variant-a", parent_kind=ParentKind.EPISODE, parent_id="episode-a", label="hd")]
```

For `ParentKind.TRACK`, build a manifest with:

```python
artists=[ManifestArtist(id="artist-a", name="North Index", layout="artist_album_disc", track_naming="track_number_title")]
albums=[ManifestAlbum(id="album-a", artist_id="artist-a", title="Winter Index")]
discs=[ManifestDisc(id="disc-a", album_id="album-a", disc_number=1)]
tracks=[ManifestTrack(id="track-a", disc_id="disc-a", track_number=1, title="Opening")]
movies=[]
series=[]
seasons=[]
episodes=[]
variants=[ManifestVariant(id="variant-a", parent_kind=ParentKind.TRACK, parent_id="track-a", label="lossless")]
```

Import the needed manifest row classes at the top of `tests/support/adapter.py`.
Update `reports()` to include the corresponding domain report map for the
selected parent kind.

- [ ] **Step 3: Emit observed rows for every domain family**

In `observed_from_fixture()` in `tests/support/adapter.py`, add refs for every
domain row:

```python
series_refs = {
    series.id: f"observed-{series.id}" for series in oracle_fixture.current_manifest.series
}
season_refs = {
    season.id: f"observed-{season.id}" for season in oracle_fixture.current_manifest.seasons
}
artist_refs = {
    artist.id: f"observed-{artist.id}" for artist in oracle_fixture.current_manifest.artists
}
album_refs = {
    album.id: f"observed-{album.id}" for album in oracle_fixture.current_manifest.albums
}
disc_refs = {
    disc.id: f"observed-{disc.id}" for disc in oracle_fixture.current_manifest.discs
}
```

Emit `ObservedSeries`, `ObservedSeason`, `ObservedEpisode`, `ObservedArtist`,
`ObservedAlbum`, `ObservedDisc`, and `ObservedTrack` lists when
`include_topology=True`. Keep empty lists when `include_topology=False`.

Update `_parent_ref_for_variant()` to use `episode_refs` and `track_refs`, which
it already accepts, and make sure those refs are populated from current
manifest rows.

- [ ] **Step 4: Verify compare remains clean for TV/music topology**

Add:

```python
def test_episode_topology_from_fixture_compares_clean() -> None:
    fixture = _fixture_for_episode()
    observed = _observed_from_fixture(fixture, include_topology=True)

    report = compare_fixture_to_observed(fixture, observed)

    assert report.ok is True
    assert report.findings == []


def test_track_topology_from_fixture_compares_clean() -> None:
    fixture = _fixture_for_track()
    observed = _observed_from_fixture(fixture, include_topology=True)

    report = compare_fixture_to_observed(fixture, observed)

    assert report.ok is True
    assert report.findings == []
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
uv run pytest tests/adapter/test_compare_final_state.py -q --no-cov
uv run pytest tests/adapter -q --no-cov
uv run ruff check tests/support/adapter.py tests/adapter/test_compare_final_state.py
uv run ruff format --check tests/support/adapter.py tests/adapter/test_compare_final_state.py
uv run ty check src tests
git diff --check
git add tests/support/adapter.py tests/adapter/test_compare_final_state.py
git commit -m "test: cover observed hierarchy topology"
```

## Task 5: Adapter Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run focused adapter and compare tests**

Run:

```bash
uv run pytest tests/adapter tests/cli/test_compare.py tests/contract/test_observed_state.py -q --no-cov
```

Expected: all selected tests pass.

- [ ] **Step 2: Run old-work adapter scan**

Run:

```bash
rg -n "Scenario\\.works|work_id|work_ref|works:|ObservedWork|ManifestWork|WorkReport|work-report|reports/works|parent_title\\|variant_label" src/chaos_librarian/adapter tests/adapter tests/support/adapter.py tests/cli/test_compare.py tests/contract/test_observed_state.py
```

Expected: no live adapter implementation references. The only acceptable
matches are negative tests in `tests/contract/test_observed_state.py` that
assert old observed-state fields are rejected. If those are the only matches,
record the exact lines in the final report.

- [ ] **Step 3: Run project gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
git diff --check
```

Expected: all commands pass with no warnings and no schema drift.
