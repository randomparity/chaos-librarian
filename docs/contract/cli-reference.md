# CLI Reference

```text
chaos-librarian validate scenario.yaml --json
chaos-librarian plan scenario.yaml --out fixtures/run-001 --json
chaos-librarian materialize scenario.yaml --out fixtures/run-001 --json
chaos-librarian run scenario.yaml --out fixtures/run-001 --duration 90s --json
chaos-librarian step fixtures/run-001 --next --json
chaos-librarian replay fixtures/run-001/replay.json --out fixtures/replay-001 --json
chaos-librarian inspect fixtures/run-001 --json
chaos-librarian capabilities --json
chaos-librarian clean fixtures/run-001 --json
```

All commands support `--json`. Exit codes:

| code | meaning                                                       |
|------|---------------------------------------------------------------|
| `0`  | success                                                       |
| `1`  | generic failure                                               |
| `2`  | usage error                                                   |
| `3`  | scenario validation failed                                    |
| `4`  | required external tool missing or version too low             |
| `5`  | materialization failed                                        |
| `6`  | replay diverged                                               |
| `7`  | filesystem safety violation (containment or sentinel)         |

Every command except `validate` ships as a Sprint 0 stub and exits `1`.
`validate` was implemented in Sprint 1. See
[`chaos-librarian-design.md` "CLI Contract"](../specs/chaos-librarian-design.md).
