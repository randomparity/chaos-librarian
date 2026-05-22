# Observed-State Contract

`observed-state.schema.json` is the consumer export format for comparing an
application's observed library state against a Chaos Librarian oracle fixture.
It is not a Chaos Librarian output artifact and it is not allowed to embed
Chaos Librarian policy expectations.

## Top-Level Shape

Required fields:

- `schema_version`: `1`
- `consumer`: `{name, version?}`
- `run_id`: the fixture run id being compared
- `observed_at`: when the consumer snapshot was exported
- `assets`: observed assets keyed by consumer-owned `observed_ref`

Optional topology and history fields:

- `works`, `variants`, `bundles`
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
  "schema_version": 1,
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

## Topology

Topology refs are consumer-owned and only need to be stable inside the payload.
When supplied, `asset.work_ref`, `asset.variant_ref`, `asset.bundle_ref`,
`variant.work_ref`, `bundle.variant_ref`, and `bundle.asset_refs` must point to
declared observed objects and agree with each other.

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
