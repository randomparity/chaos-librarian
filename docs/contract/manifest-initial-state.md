# Initial-Manifest Convention

`manifest.initial.json` describes the expected library state at `t=0`,
*before* any timeline event has applied. The plan-only engine synthesizes the
initial state from the explicit domain hierarchy in the scenario:
`movies[*].variants`, `series[*].seasons[*].episodes[*].variants`, and
`artists[*].albums[*].discs[*].tracks[*].variants`.

Initial asset paths are rendered from the root path, the selected
movie/series/artist layout, the leaf metadata, the variant label, and the asset
container. The initial manifest uses this convention:

- One `Version` per asset (`version_NNNN`, monotonic allocator counter,
  `index = 0`).
- One `Location` per asset (`location_NNNN`, monotonic allocator counter).
  The concrete path shape is determined by the owning movie, episode, or track
  layout and naming policy.

Rendered media paths use normalized display text from the domain hierarchy,
the variant label, and the asset container:

- `movie_flat`: `<root>/<movie title> - <variant label>.<container>`
- `movie_folder`: `<root>/<movie title>/<movie title> - <variant label>.<container>`
- `season_folders`:
  `<root>/<series title>/Season NN/<episode stem> - <variant label>.<container>`
- `series_flat`:
  `<root>/<series title>/<episode stem> - <variant label>.<container>`
- `artist_album_disc`:
  `<root>/<artist name>/<album title>/Disc NN/<track stem> - <variant label>.<container>`
- `artist_album_flat`:
  `<root>/<artist name>/<album title>/<track stem> - <variant label>.<container>`

For example, these scenario values render to these initial `Location.path`
values:

- Movie: root `Movies`, title `Orbit`, layout `movie_flat`, variant `1080p`,
  asset container `mkv` -> `Movies/Orbit - 1080p.mkv`.
- TV: root `TV`, series `Starline`, season `1`, episode `1`, title `Pilot`,
  layout `season_folders`, naming `sxxexx_title`, variant `1080p`, asset
  container `mkv` -> `TV/Starline/Season 01/Starline - S01E01 - Pilot - 1080p.mkv`.
- Music: root `Music`, artist `North Index`, album `Winter Index`, disc `1`,
  track `1`, title `Opening`, layout `artist_album_disc`, naming
  `track_number_title`, variant `lossless`, asset container `flac` ->
  `Music/North Index/Winter Index/Disc 01/01 - Opening - lossless.flac`.

Episode stems are selected by `episode_naming`: `S01E02`, `1x02`,
three-digit absolute number, or ISO air date forms. Track stems are selected by
`track_naming`: `02 - Title` or `01-02 - Title`. Multi-asset bundles add the
asset role before the extension.

- Declared subtitle tracks with `mode: sidecar` create initial sidecars.
  Additional sidecars are created by explicit `create_sidecar` timeline events.

Authors who want a custom starting path should declare the asset normally and
add a `move_asset` timeline event at `t=0`. Do not use `add_file` for this:
`add_file` represents restoration of an asset that is currently absent and
validation rejects `add_file` on an already-placed asset.

See [`chaos-librarian-design.md`](../specs/chaos-librarian-design.md)
§"Manifest Model" for the full schema.
