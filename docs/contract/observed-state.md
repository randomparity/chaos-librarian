# Observed-State Contract

`observed-state.schema.json` is the consumer export format for comparing an
application's observed library state against a Chaos Librarian oracle fixture.
It is not a Chaos Librarian output artifact and it is not allowed to embed
Chaos Librarian policy expectations.

## Top-Level Shape

Required fields:

- `schema_version`: `2`
- `consumer`: `{name, version?}`
- `run_id`: the fixture run id being compared
- `observed_at`: when the consumer snapshot was exported
- `assets`: observed assets keyed by consumer-owned `observed_ref`

Optional topology and history fields:

- `movies`, `series`, `seasons`, `episodes`
- `artists`, `albums`, `discs`, `tracks`
- `variants`, `bundles`
- `events`
- per-asset `sidecars`
- per-asset `path_history`

All paths are library-relative POSIX paths. Exporters must strip local mount
prefixes and must not emit absolute paths, backslashes, empty segments, `.`, or
`..`.

## Examples

Scanner-only minimal asset:

```json
{
  "schema_version": 2,
  "consumer": {"name": "scanner"},
  "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
  "observed_at": "2026-05-22T12:00:00Z",
  "assets": [
    {"observed_ref": "asset-1", "current_path": "movies/Synthetic.mkv"}
  ]
}
```

Prober evidence adds hashes and media facts:

```json
{
  "observed_ref": "asset-1",
  "current_path": "movies/Synthetic.mkv",
  "content_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "probed": {
    "container": "matroska,webm",
    "duration_seconds": 60.0,
    "size_bytes": 12345,
    "streams": [{"kind": "video", "codec": "h264", "width": 1920, "height": 1080}]
  }
}
```

Watcher evidence can be attached to an asset:

```json
{
  "observed_ref": "asset-1",
  "current_path": "movies/Renamed.mkv",
  "path_history": [
    {
      "action": "rename_file",
      "from_path": "movies/Synthetic.mkv",
      "to_path": "movies/Renamed.mkv"
    }
  ]
}
```

Or emitted as global events:

```json
{
  "events": [
    {
      "observed_event_ref": "event-1",
      "observed_ref": "asset-1",
      "action": "rename_file",
      "from_path": "movies/Synthetic.mkv",
      "to_path": "movies/Renamed.mkv"
    }
  ]
}
```

Hierarchy path moves use their hierarchy action names in the same lifecycle
shape, with `from_path` and `to_path` populated.

## Probe And Sidecar Normalization

Unknown stream language can appear differently across containers and ffprobe
snapshots.

During `compare`, JSON `null`, omitted language, and `und` are equivalent for
audio and video streams.

Consumers should export the facts they observed rather than synthesizing
container-specific language guesses.

Subtitle streams remain strict because subtitle language is assertion data. A
subtitle stream with missing language does not compare equal to `und`, `eng`, or
any other concrete tag.

Sidecars are nested under their owning asset and use library-relative POSIX path
values. Observed sidecars do not carry a separate language field; subtitle
sidecar language is represented by the path convention when applicable.

```json
{
  "observed_ref": "asset-1",
  "current_path": "movies/Synthetic.mkv",
  "probed": {
    "container": "matroska,webm",
    "duration_seconds": 60.0,
    "size_bytes": 12345,
    "streams": [
      {"kind": "video", "codec": "h264", "width": 1920, "height": 1080},
      {"kind": "audio", "codec": "aac", "language": "und", "channels": 2}
    ]
  },
  "sidecars": [
    {
      "observed_ref": "sidecar-1",
      "kind": "subtitle",
      "path": "asset-1.eng.srt",
      "content_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
  ]
}
```

## Topology

Topology refs are consumer-owned and only need to be stable inside the payload.
Observed-state v2 has these domain row families:

- `movies`
- `series`
- `seasons`
- `episodes`
- `artists`
- `albums`
- `discs`
- `tracks`
- `variants`
- `bundles`
- `assets`
- `sidecars`

Rows for seasons, episodes, albums, discs, and tracks point to their immediate
parent row. Variant rows point to one playable or listenable parent with
`parent_kind` (`movie`, `episode`, or `track`) and `parent_ref`. Bundle rows can
point to a variant and list asset refs. Asset rows always carry `observed_ref`
and `current_path`; they carry `variant_ref` and `bundle_ref` only when the
consumer can provide those links. When supplied, topology refs must point to
declared observed objects and agree with each other.

Movie topology:

```json
{
  "schema_version": 2,
  "consumer": {"name": "scanner"},
  "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
  "observed_at": "2026-05-22T12:00:00Z",
  "movies": [{"observed_ref": "movie-1", "title": "Synthetic Quasar"}],
  "variants": [
    {
      "observed_ref": "variant-1",
      "parent_kind": "movie",
      "parent_ref": "movie-1",
      "label": "hd"
    }
  ],
  "bundles": [
    {
      "observed_ref": "bundle-1",
      "variant_ref": "variant-1",
      "asset_refs": ["asset-1"]
    }
  ],
  "assets": [
    {
      "observed_ref": "asset-1",
      "current_path": "movies/Synthetic Quasar.mkv",
      "variant_ref": "variant-1",
      "bundle_ref": "bundle-1"
    }
  ]
}
```

TV and music topology use the same ref rules with deeper parents:

```json
{
  "series": [{"observed_ref": "series-1", "title": "Atlas Station"}],
  "seasons": [
    {"observed_ref": "season-1", "series_ref": "series-1", "season_number": 1}
  ],
  "episodes": [
    {"observed_ref": "episode-1", "season_ref": "season-1", "episode_number": 1}
  ],
  "artists": [{"observed_ref": "artist-1", "name": "Glass Harbour"}],
  "albums": [{"observed_ref": "album-1", "artist_ref": "artist-1"}],
  "discs": [{"observed_ref": "disc-1", "album_ref": "album-1", "disc_number": 1}],
  "tracks": [
    {"observed_ref": "track-1", "disc_ref": "disc-1", "track_number": 1}
  ]
}
```

Bundle sidecar refs are scoped by both asset and sidecar:

```json
{"asset_ref": "asset-1", "sidecar_ref": "sidecar-1"}
```

The referenced `asset_ref` must be listed in that bundle's `asset_refs`, and
the `sidecar_ref` must exist under that asset's nested `sidecars`.

## Input Errors

`load_observed_state()` raises `E_ADAPTER_OBSERVED_INVALID` for malformed JSON,
schema violations, duplicate refs, invalid paths, dangling or contradictory
topology refs, missing per-action path fields, invalid global event identity
evidence, and invalid grouped lifecycle links.
