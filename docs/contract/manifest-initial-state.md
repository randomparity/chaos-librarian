# Initial-Manifest Convention

`manifest.initial.json` describes the expected library state at `t=0`,
*before* any timeline event has applied. Sprint 3's plan-only engine
synthesizes the initial state from the scenario's
`works[*].variants[*].bundle.assets[*]` declarations using this convention:

- One `Version` per asset (`version_NNNN`, monotonic allocator counter,
  `index = 0`).
- One `Location` per asset (`location_NNNN`, monotonic allocator
  counter), at path:

  ```
  <library.roots[0].path>/<asset.id>.<asset.container>
  ```

- No `Sidecar`s at `t=0`; sidecars are created by explicit
  `create_sidecar` timeline events.

Authors who want a custom initial path should use an `add_file` timeline
event at `t=0` after the asset is declared. Sprint 3 does NOT yet ship a
scenario-level "initial path" override; it lands in a later sprint if a
fixture genuinely needs it.

See [`chaos-librarian-design.md`](../specs/chaos-librarian-design.md)
§"Manifest Model" for the full schema.
