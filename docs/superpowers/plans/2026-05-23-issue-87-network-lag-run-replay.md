# Issue 87 Network Lag Run Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow run-mode replay bundles with network-lag journal entries to replay successfully and emit network-lag audit evidence.

**Architecture:** Keep wall-clock timing out of replay. Let replay accept network-lag timelines, skip lag start/commit entries in ordinary phase-B dispatch, and translate them into `NetworkLagAction` rows on the replay materialization report.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ruff, ty.

---

### Task 1: Replay Regression Test

**Files:**
- Modify: `tests/materializer/test_replay.py`

- [ ] **Step 1: Add a network-lag replay scenario**

Add this constant near the other scenario constants:

```python
_NETWORK_LAG_SCENARIO = _scenario_bytes(
    scenario_id="run-replay-network-lag-test",
    profiles=("network-fs-lag",),
    title="Network Lag Replay",
    timeline="""\
  - id: rename_001
    at: 0ns
    action: rename_file
    target: asset_main
    to: movies-hd/renamed.mkv
  - id: lag_start_001
    at: 0ns
    action: network_lag_start
    effect: delayed_rename
    target: asset_main
    after: rename_001
    duration: 10ns
  - id: lag_commit_001
    at: 10ns
    action: network_lag_commit
    for: lag_start_001
""",
)
```

- [ ] **Step 2: Add the failing test**

Add this test:

```python
def test_run_replay_reproduces_network_lag_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_replay_materializer(monkeypatch)
    out = tmp_path / "replay"

    artifacts = replay_run_bundle(
        _run_bundle_for(_NETWORK_LAG_SCENARIO, applied_events=3),
        out,
    )

    assert (out / "library" / "movies-hd" / "renamed.mkv").read_bytes() == (
        b"asset_main-bytes"
    )
    action = artifacts.materialization_report.network_lag_actions[0]
    assert action.event_id == "lag_start_001"
    assert action.commit_event_id == "lag_commit_001"
    assert action.effect.value == "delayed_rename"
    assert action.after_event_id == "rename_001"
    assert action.from_path == "movies-hd/asset_main.mkv"
    assert action.to_path == "movies-hd/renamed.mkv"
    assert action.provider == "stdlib-local"
    assert action.enforced is True

    report_payload = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    assert report_payload["network_lag_actions"][0]["event_id"] == "lag_start_001"
```

- [ ] **Step 3: Verify RED**

Run:

```bash
uv run pytest tests/materializer/test_replay.py::test_run_replay_reproduces_network_lag_evidence -q --no-cov
```

Expected: FAIL with `TimelineUnsupportedError` for `network_lag_start`.

### Task 2: Replay Network-Lag Handling

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Test: `tests/materializer/test_replay.py`

- [ ] **Step 1: Add network-lag evidence storage to PhaseBState**

Import `NetworkLagAction` from `chaos_librarian.contract.materialization` and add:

```python
    network_lag_actions: list[NetworkLagAction] = field(default_factory=list)
```

to `PhaseBState`.

- [ ] **Step 2: Allow network-lag preflight in run replay**

Change replay preflight to:

```python
preflight_timeline(scenario, allow_network_lag=True)
```

- [ ] **Step 3: Convert replay lag entries into evidence**

Import `CommittedJournalEntry`, `JournalEntry`, `NetworkLagAction`,
`NetworkLagEffect`, and `TimelineActionName` as needed. Replace
`_apply_prefix_phase_b()` with a loop that stores starts, converts commits, and
dispatches all ordinary entries:

```python
def _apply_prefix_phase_b(
    state: PhaseBState,
    artifacts: PlanArtifacts,
) -> None:
    network_lag_starts: dict[str, JournalEntry] = {}
    for entry in artifacts.journal:
        action = TimelineActionName(entry.action)
        if action is TimelineActionName.NETWORK_LAG_START:
            network_lag_starts[entry.event_id] = entry
            continue
        if action is TimelineActionName.NETWORK_LAG_COMMIT:
            state.network_lag_actions.append(
                _run_replay_network_lag_action(network_lag_starts, entry)
            )
            continue
        dispatch_phase_b_entry(state, entry)
    if network_lag_starts:
        pending = sorted(network_lag_starts)
        raise ReplayIntegrityError(f"uncommitted network_lag_start entries: {pending}")
```

Add these helpers:

```python
def _run_replay_network_lag_action(
    starts: dict[str, JournalEntry],
    commit: JournalEntry,
) -> NetworkLagAction:
    if not isinstance(commit, CommittedJournalEntry):
        raise ReplayIntegrityError(f"{commit.event_id} is not a committed network lag entry")
    start = starts.pop(commit.related_event_id, None)
    if start is None:
        raise ReplayIntegrityError(
            f"network_lag_commit {commit.event_id} references missing start "
            f"{commit.related_event_id}"
        )
    effect = _network_lag_effect(start)
    return NetworkLagAction(
        event_id=start.event_id,
        commit_event_id=commit.event_id,
        effect=effect,
        target_ref=_network_lag_str(start, "target_ref"),
        after_event_id=_network_lag_str(start, "after_event_id"),
        logical_start_ns=_network_lag_int(start, "logical_start_ns"),
        logical_commit_ns=_network_lag_int(start, "logical_commit_ns"),
        requested_duration_ns=_network_lag_int(start, "requested_duration_ns"),
        actual_duration_ns=None,
        from_path=_network_lag_optional_str(start, "from_path"),
        to_path=_network_lag_optional_str(start, "to_path"),
        provider="stdlib-local",
        enforced=effect is not NetworkLagEffect.HELD_HANDLE,
    )


def _network_lag_effect(entry: JournalEntry) -> NetworkLagEffect:
    return NetworkLagEffect(_network_lag_str(entry, "effect"))


def _network_lag_str(entry: JournalEntry, key: str) -> str:
    value = entry.state_delta.get(key)
    if not isinstance(value, str):
        raise ReplayIntegrityError(f"{entry.event_id}: missing network-lag {key}")
    return value


def _network_lag_optional_str(entry: JournalEntry, key: str) -> str | None:
    value = entry.state_delta.get(key)
    if value is None or isinstance(value, str):
        return value
    raise ReplayIntegrityError(f"{entry.event_id}: invalid network-lag {key}")


def _network_lag_int(entry: JournalEntry, key: str) -> int:
    value = entry.state_delta.get(key)
    if isinstance(value, int):
        return value
    raise ReplayIntegrityError(f"{entry.event_id}: missing network-lag {key}")
```

- [ ] **Step 4: Include network-lag actions in replay reports**

Pass `network_lag_actions=state.network_lag_actions` to both success and
phase-B failure `build_report()` calls in `materializer.replay`.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
uv run pytest tests/materializer/test_replay.py::test_run_replay_reproduces_network_lag_evidence -q --no-cov
```

Expected: PASS.

### Task 3: Focused Verification

**Files:**
- Modify: `src/chaos_librarian/engine/diff.py`
- Modify: `tests/cli/test_replay.py`

- [ ] **Step 1: Add compare regression tests**

Add a `_network_lag_action()` helper in `tests/cli/test_replay.py`:

```python
def _network_lag_action(
    *,
    effect: str = "delayed_rename",
    actual_duration_ns: int | None = 1,
) -> dict[str, object]:
    action = {
        "event_id": "lag_start_001",
        "commit_event_id": "lag_commit_001",
        "effect": effect,
        "target_ref": "asset_main",
        "after_event_id": "rename_001",
        "logical_start_ns": 0,
        "logical_commit_ns": 10,
        "requested_duration_ns": 10,
        "actual_duration_ns": actual_duration_ns,
        "from_path": "movies-hd/asset_main.mkv",
        "to_path": "movies-hd/renamed.mkv",
        "provider": "stdlib-local",
        "enforced": True,
    }
    return {key: value for key, value in action.items() if value is not None}
```

Add these tests:

```python
def test_compare_run_replay_compares_network_lag_actions(tmp_path: Path) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _update_materialization(left, "network_lag_actions", [_network_lag_action()])
    _update_materialization(
        right,
        "network_lag_actions",
        [_network_lag_action(effect="delayed_visibility")],
    )

    diff = compare_run_replay(left, right)

    assert [item.path for item in diff.files] == ["materialization.json"]


def test_compare_run_replay_ignores_network_lag_actual_duration(
    tmp_path: Path,
) -> None:
    left = _write_run_compare_fixture(tmp_path / "left")
    right = _write_run_compare_fixture(tmp_path / "right")
    _update_materialization(
        left,
        "network_lag_actions",
        [_network_lag_action(actual_duration_ns=10)],
    )
    _update_materialization(
        right,
        "network_lag_actions",
        [_network_lag_action(actual_duration_ns=None)],
    )

    diff = compare_run_replay(left, right)

    assert diff.is_clean()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/cli/test_replay.py::test_compare_run_replay_compares_network_lag_actions tests/cli/test_replay.py::test_compare_run_replay_ignores_network_lag_actual_duration -q --no-cov
```

Expected: FAIL because network-lag actions are not included in normalized
`materialization.json` comparisons.

- [ ] **Step 3: Include normalized network-lag actions**

In `src/chaos_librarian/engine/diff.py`, add
`"network_lag_actions": _normalize_network_lag_action_list(...)` to
`_normalize_materialization_for_run_replay()`, and add:

```python
def _normalize_network_lag_action_list(value: object) -> list[object]:
    actions = _list_or_empty(value)
    normalized: list[object] = []
    for action in actions:
        action_data = _str_keyed_dict(action)
        if action_data is None:
            normalized.append(action)
            continue
        normalized_action = dict(action_data)
        normalized_action.pop("actual_duration_ns", None)
        normalized.append(normalized_action)
    return normalized
```

- [ ] **Step 4: Verify GREEN**

Run the two compare tests again. Expected: PASS.

### Task 4: Focused Verification

**Files:**
- Test: `tests/materializer/test_replay.py`
- Test: `tests/materializer/test_preflight.py`
- Test: `tests/cli/test_replay.py`

- [ ] **Step 1: Run focused replay/preflight suites**

Run:

```bash
uv run pytest tests/materializer/test_replay.py tests/materializer/test_preflight.py tests/cli/test_replay.py -q --no-cov
```

Expected: PASS.

- [ ] **Step 2: Run static checks and schema drift gate**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands exit 0 with no warnings.
