# Initial-Manifest Convention

`manifest.initial.json` describes the expected library state at `t=0`,
*before* any timeline event has applied. The plan-only engine synthesizes the
initial state from the scenario's
`works[*].variants[*].bundle.assets[*]` declarations using this convention:

- One `Version` per asset (`version_NNNN`, monotonic allocator counter,
  `index = 0`).
- One `Location` per asset (`location_NNNN`, monotonic allocator
  counter), at path:

  ```
  <library.roots[0].path>/<asset.id>.<asset.container>
  ```

- Declared subtitle tracks with `mode: sidecar` create initial sidecars.
  Additional sidecars are created by explicit `create_sidecar` timeline events.

Authors who want a custom starting path should declare the asset normally and
add a `move_asset` timeline event at `t=0`. Do not use `add_file` for this:
`add_file` represents restoration of an asset that is currently absent and
validation rejects `add_file` on an already-placed asset.

See [`chaos-librarian-design.md`](../specs/chaos-librarian-design.md)
§"Manifest Model" for the full schema.
