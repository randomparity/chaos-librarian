# Adapter Compare

The adapter layer compares a neutral Chaos Librarian oracle with a consumer's
exported observed state. It does not know the consumer database schema.

`load_fixture` reads oracle artifacts from a run directory. It validates the
sentinel, replay bundle, stored scenario bytes, manifests, and journal identity
and digest. `reports/` is required adapter input; every report family directory
and report ID must match the manifest exactly.

`load_observed_state` reads consumer JSON and validates it against the
`ObservedState` contract.

`compare_fixture_to_observed` emits a `DivergenceReport`. It checks run identity,
builds oracle and observed indexes, matches assets, compares current paths,
content hashes, probe fields, sidecars, and topology when supplied, then adds
identity-history checks when requested.

`final-state` mode checks the current expected library state. It is the right
mode for scanner and prober tests that only care about the final fixture.

`identity-history` mode also checks lifecycle evidence through asset path
history or global observed events. It is the right mode for watcher and durable
identity tests.
