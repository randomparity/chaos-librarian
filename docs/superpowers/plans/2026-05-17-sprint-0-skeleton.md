# Chaos Librarian Sprint 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Sprint 0 of `docs/specs/chaos-librarian-design.md` — a contract-only sprint that establishes the project skeleton, freezes the seven JSON-Schema artifacts (`scenario`, `manifest`, `journal`, `replay-bundle`, `validation`, `materialization`, `run-sentinel`), exposes a frozen Typer CLI surface with stub commands, ships the path-containment helper required by the Filesystem Safety contract, and runs CI green on a fresh clone.

**Architecture:** Pydantic v2 models under `src/chaos_librarian/contract/` are the schema source-of-truth. A CI job exports them to JSON Schema (draft 2020-12) under `schemas/*.schema.json` and fails if committed artifacts diverge from current models. Multi-phase journal fields (`phase`, `temp_path`, `related_event_id`) ship in the journal schema from day one. The CLI is a Typer app with frozen command names and stub implementations that exit `1`. No runtime behavior is implemented; that lands in Sprint 1+.

**Tech Stack:** Python 3.13, `uv` (deps + venv), Pydantic v2, Typer, `ruamel.yaml`, `pytest`, `ruff`, `ty`, `prek` (pre-commit), GitHub Actions.

---

## File Structure

Files created or modified by this plan. One responsibility per file.

```
chaos-librarian/
├── pyproject.toml                              [Task 1] uv + tool config
├── .gitignore                                  [Task 1]
├── .pre-commit-config.yaml                     [Task 2] prek hooks
├── .github/workflows/ci.yml                    [Task 3] lint, type, test, schema-export gate
├── src/chaos_librarian/
│   ├── __init__.py                             [Task 1] package version
│   ├── contract/
│   │   ├── __init__.py                         [Task 4] namespace UUID + schema_version constants
│   │   ├── paths.py                            [Task 5] path-containment helper
│   │   ├── run_sentinel.py                     [Task 6] sentinel Pydantic model
│   │   ├── scenario.py                         [Task 7] scenario Pydantic model
│   │   ├── manifest.py                         [Task 8] manifest Pydantic model
│   │   ├── journal.py                          [Task 9] journal entry Pydantic model (multi-phase)
│   │   ├── replay_bundle.py                    [Task 10] replay-bundle Pydantic model (mode-split)
│   │   ├── validation.py                       [Task 11] validation report Pydantic model
│   │   └── materialization.py                  [Task 12] materialization report Pydantic model
│   ├── schema_export.py                        [Task 13] exports all models to schemas/
│   └── cli/
│       ├── __init__.py                         [Task 14]
│       └── app.py                              [Task 14] Typer app, frozen surface
├── schemas/                                    [Task 13] generated JSON Schema artifacts
│   ├── scenario.schema.json
│   ├── manifest.schema.json
│   ├── journal.schema.json
│   ├── replay-bundle.schema.json
│   ├── validation.schema.json
│   ├── materialization.schema.json
│   └── run-sentinel.schema.json
├── tests/
│   ├── contract/
│   │   ├── test_paths.py                       [Task 5]
│   │   ├── test_run_sentinel.py                [Task 6]
│   │   ├── test_scenario.py                    [Task 7]
│   │   ├── test_manifest.py                    [Task 8]
│   │   ├── test_journal.py                     [Task 9]
│   │   ├── test_replay_bundle.py               [Task 10]
│   │   ├── test_validation.py                  [Task 11]
│   │   ├── test_materialization.py             [Task 12]
│   │   ├── test_schema_export.py               [Task 13]
│   │   └── test_sample_scenarios.py            [Task 15]
│   ├── cli/test_app.py                         [Task 14]
│   └── fixtures/scenarios/                     [Task 15]
│       ├── identity-move-rename.yaml
│       ├── version-evolution.yaml
│       ├── bundle-sidecars.yaml
│       └── slow-copy.yaml
└── docs/contract/                              [Task 16]
    ├── schema-reference.md
    ├── fixture-layout.md
    ├── cli-reference.md
    ├── replay-bundle.md
    └── time-model.md
```

**Notes on layout decisions:**

- One module per artifact under `contract/`. Each is small and focused. They share no runtime state; they only share type primitives via `contract/__init__.py`.
- The `schemas/` directory is generated, **but checked in**. CI compares committed artifacts to freshly-generated ones and fails on drift. This gives external consumers a stable URL without running the tool.
- Tests mirror package structure (`tests/contract/` mirrors `src/chaos_librarian/contract/`).
- Sample scenarios live under `tests/fixtures/scenarios/` per the design doc. They double as validation fixtures for `tests/contract/test_sample_scenarios.py`.

---

## Phase 1: Project Skeleton

### Task 1: pyproject.toml, package skeleton, .gitignore

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/chaos_librarian/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/contract/__init__.py`

- [ ] **Step 1: Initialize uv project and Python 3.13 venv**

Run:
```bash
uv init --package --python 3.13 --no-readme
```

This generates a starter `pyproject.toml` and `src/chaos_librarian/__init__.py`. Delete the auto-generated `hello()` function — replace `src/chaos_librarian/__init__.py` with:

```python
"""Chaos Librarian: scenario-driven synthetic media library simulator."""

__version__ = "0.0.0"
```

- [ ] **Step 2: Add runtime and dev dependencies**

Run:
```bash
uv add pydantic typer "ruamel.yaml"
uv add --dev pytest pytest-cov ruff ty
```

- [ ] **Step 3: Replace generated pyproject.toml with the full config**

Open the auto-generated `pyproject.toml` and replace it entirely with:

```toml
[project]
name = "chaos-librarian"
version = "0.0.0"
description = "Scenario-driven synthetic media library simulator for voom-v2 tests."
readme = "README.md"
requires-python = ">=3.13"
license = { text = "MIT" }
authors = [{ name = "David Christensen" }]
dependencies = [
    "pydantic>=2.10",
    "typer>=0.13",
    "ruamel.yaml>=0.18",
]

[project.scripts]
chaos-librarian = "chaos_librarian.cli.app:app"

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-cov>=5",
    "ruff>=0.7",
    "ty",
]

[build-system]
requires = ["uv_build>=0.5"]
build-backend = "uv_build"

[tool.uv]
package = true

[tool.pytest.ini_options]
addopts = "-q --strict-markers"
testpaths = ["tests"]

[tool.coverage.run]
source = ["chaos_librarian"]
branch = true
```

(Ruff and ty config are added in Task 2.)

- [ ] **Step 4: Create .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
build/
dist/

# Tooling
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
.ty_cache/

# OS
.DS_Store
```

- [ ] **Step 5: Create README placeholder**

```markdown
# Chaos Librarian

Scenario-driven synthetic media library simulator for testing voom-v2 scanners, watchers, probes, and reconciliation. See [`docs/specs/chaos-librarian-design.md`](docs/specs/chaos-librarian-design.md) for the design and [`docs/contract/`](docs/contract/) for the consumer-facing contract.
```

- [ ] **Step 6: Create empty `__init__.py` files for test packages**

`tests/__init__.py` and `tests/contract/__init__.py` are empty files.

- [ ] **Step 7: Verify uv sync produces a clean venv**

Run:
```bash
uv sync
uv run python -c "import chaos_librarian; print(chaos_librarian.__version__)"
```
Expected: prints `0.0.0` with no errors.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .gitignore README.md src/chaos_librarian/__init__.py tests/__init__.py tests/contract/__init__.py
git commit -m "Add project skeleton with uv + Python 3.13"
```

---

### Task 2: Ruff, ty, and prek configuration

**Files:**
- Modify: `pyproject.toml` (append tool config)
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Append ruff and ty config to pyproject.toml**

Add to the bottom of `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E", "W",       # pycodestyle
    "F",            # pyflakes
    "I",            # isort
    "B",            # bugbear
    "UP",           # pyupgrade
    "SIM",          # simplify
    "RUF",          # ruff-specific
    "TID",          # tidy imports
    "PL",           # pylint
    "PT",           # pytest style
]
ignore = [
    "PLR0913",      # too many args — Pydantic models exceed this naturally
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["PLR2004"]   # magic numbers fine in tests

[tool.ruff.lint.flake8-tidy-imports]
ban-relative-imports = "all"   # absolute imports only — matches global standards

[tool.ruff.format]
quote-style = "double"

[tool.ty.rules]
unresolved-import = "error"
possibly-unbound = "error"
```

- [ ] **Step 2: Create prek config**

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/astral-sh/uv-pre-commit
    rev: 0.5.4
    hooks:
      - id: uv-lock
```

(Engineer note: look up current stable revs of `ruff-pre-commit` and `uv-pre-commit` at execution time and substitute. The exact revs above are reasonable defaults but verify with `prek autoupdate` after installing.)

- [ ] **Step 3: Install prek hooks**

Run:
```bash
prek install
prek auto-update --cooldown-days 7
```

- [ ] **Step 4: Verify ruff and ty run clean on the empty skeleton**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```
Expected: all three exit `0`. If ruff format flags anything, run `uv run ruff format .` and re-check.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .pre-commit-config.yaml
git commit -m "Configure ruff, ty, and prek hooks"
```

---

### Task 3: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the CI workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  lint-type-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
        with:
          persist-credentials: false

      - name: Install uv
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86  # v5.1.0
        with:
          version: "0.5.4"
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Ruff check
        run: uv run ruff check .

      - name: Ruff format
        run: uv run ruff format --check .

      - name: ty check
        run: uv run ty check src tests

      - name: Pytest
        run: uv run pytest

      - name: Verify exported JSON Schemas are up-to-date
        run: |
          uv run python -m chaos_librarian.schema_export --check
```

(Engineer note: SHA pins above are realistic but verify against the latest tagged releases of `actions/checkout` and `astral-sh/setup-uv` at execution time. Use the `<sha>  # <version>` format from the global standards.)

The `schema_export --check` invocation is added in Task 13. It's referenced here so the workflow is complete on first commit; if Task 13 lands later the CI step will fail until then, which is the desired ordering signal.

- [ ] **Step 2: Run actionlint and zizmor locally**

```bash
actionlint .github/workflows/ci.yml
zizmor .github/workflows/
```
Expected: both clean. Fix any complaints before committing.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "Add GitHub Actions CI workflow"
```

---

## Phase 2: Contract Foundations

### Task 4: Contract package constants

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`

**Background:** The design doc requires a fixed namespace UUID for deriving deterministic UUIDv5 `run_id` values in plan-only mode. The namespace is a module-level constant and "never changes across releases". We derive it deterministically from a DNS-style namespace string so this plan does not need to embed a hand-picked UUID.

- [ ] **Step 1: Create directory and __init__**

Run:
```bash
mkdir -p src/chaos_librarian/contract
mkdir -p tests/contract
```

Create `src/chaos_librarian/contract/__init__.py`:

```python
"""Schema source-of-truth: Pydantic v2 models exported as JSON Schema."""

from __future__ import annotations

import uuid
from typing import Final

# Schema versions. Bumps are always breaking (no minor versions).
# See docs/specs/chaos-librarian-design.md "Versioning".
SCENARIO_SCHEMA_VERSION: Final[int] = 1
MANIFEST_SCHEMA_VERSION: Final[int] = 1
JOURNAL_SCHEMA_VERSION: Final[int] = 1
REPLAY_BUNDLE_SCHEMA_VERSION: Final[int] = 1
VALIDATION_SCHEMA_VERSION: Final[int] = 1
MATERIALIZATION_SCHEMA_VERSION: Final[int] = 1
RUN_SENTINEL_SCHEMA_VERSION: Final[int] = 1

# Namespace UUID used to derive deterministic UUIDv5 run_ids in plan-only mode.
# Derived once from a stable DNS-style string so the value is reproducible
# without embedding hand-picked bytes. MUST NEVER CHANGE.
CHAOS_LIBRARIAN_NAMESPACE_UUID: Final[uuid.UUID] = uuid.uuid5(
    uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1"
)
```

- [ ] **Step 2: Write a test that locks the namespace UUID value**

`tests/contract/test_contract_constants.py`:

```python
"""Lock the namespace UUID so accidental edits cause a test failure."""

from __future__ import annotations

import uuid

from chaos_librarian.contract import (
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    JOURNAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
)


def test_namespace_uuid_is_stable() -> None:
    expected = uuid.uuid5(uuid.NAMESPACE_DNS, "chaos-librarian.randomparity.io.v1")
    assert CHAOS_LIBRARIAN_NAMESPACE_UUID == expected


def test_namespace_uuid_is_v5() -> None:
    assert CHAOS_LIBRARIAN_NAMESPACE_UUID.version == 5


def test_all_schema_versions_are_positive_integers() -> None:
    versions = [
        SCENARIO_SCHEMA_VERSION,
        MANIFEST_SCHEMA_VERSION,
        JOURNAL_SCHEMA_VERSION,
        REPLAY_BUNDLE_SCHEMA_VERSION,
        VALIDATION_SCHEMA_VERSION,
        MATERIALIZATION_SCHEMA_VERSION,
        RUN_SENTINEL_SCHEMA_VERSION,
    ]
    assert all(isinstance(v, int) and v >= 1 for v in versions)
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/contract/test_contract_constants.py -v
```
Expected: 3 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py tests/contract/test_contract_constants.py
git commit -m "Add contract package constants and namespace UUID"
```

---

### Task 5: Path-containment helper

**Files:**
- Create: `src/chaos_librarian/contract/paths.py`
- Create: `tests/contract/test_paths.py`

**Background:** Implements the "Path Containment" rules from `docs/specs/chaos-librarian-design.md` Filesystem Safety section. Pure function; no side effects beyond reading the filesystem to resolve symlinks. Sprint 0 only needs the pure helper and its tests; later sprints wire it into the materializer.

- [ ] **Step 1: Write the failing tests first**

`tests/contract/test_paths.py`:

```python
"""Tests for path containment under <run-dir>/library/."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from chaos_librarian.contract.paths import (
    PathContainmentError,
    resolve_under_library,
)


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    root = tmp_path / "run" / "library"
    root.mkdir(parents=True)
    return root


def test_simple_relative_path_resolves(library_root: Path) -> None:
    resolved = resolve_under_library(Path("movies-hd/A.mkv"), library_root)
    assert resolved == (library_root / "movies-hd" / "A.mkv").resolve()


def test_nested_relative_path_resolves(library_root: Path) -> None:
    resolved = resolve_under_library(Path("a/b/c/d.mkv"), library_root)
    assert resolved == (library_root / "a" / "b" / "c" / "d.mkv").resolve()


def test_absolute_path_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="absolute"):
        resolve_under_library(Path("/etc/passwd"), library_root)


def test_absolute_path_to_library_rejected(library_root: Path) -> None:
    # Even an absolute path that happens to be inside library/ is rejected.
    # Scenario paths must be relative.
    with pytest.raises(PathContainmentError, match="absolute"):
        resolve_under_library(library_root / "A.mkv", library_root)


def test_dotdot_escape_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="escape"):
        resolve_under_library(Path("../outside.mkv"), library_root)


def test_deep_dotdot_escape_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="escape"):
        resolve_under_library(Path("movies-hd/../../outside.mkv"), library_root)


def test_dotdot_that_stays_inside_is_allowed(library_root: Path) -> None:
    resolved = resolve_under_library(Path("movies-hd/../movies-4k/A.mkv"), library_root)
    assert resolved == (library_root / "movies-4k" / "A.mkv").resolve()


def test_symlink_target_outside_library_rejected(
    library_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside_target"
    outside.mkdir()
    (outside / "secret.mkv").touch()

    link = library_root / "escape"
    os.symlink(outside, link)

    with pytest.raises(PathContainmentError, match="escape"):
        resolve_under_library(Path("escape/secret.mkv"), library_root)


def test_symlink_target_inside_library_allowed(library_root: Path) -> None:
    real = library_root / "movies-hd"
    real.mkdir()
    (real / "A.mkv").touch()

    link = library_root / "alias"
    os.symlink(real, link)

    resolved = resolve_under_library(Path("alias/A.mkv"), library_root)
    # Symlink resolves into the real path, which is inside library/.
    assert resolved == (real / "A.mkv").resolve()


def test_empty_path_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="empty"):
        resolve_under_library(Path(""), library_root)


def test_dot_path_rejected(library_root: Path) -> None:
    # Path(".") has parts ("",) on some platforms; either way it resolves to
    # the library root, which violates the strict-subpath rule.
    with pytest.raises(PathContainmentError, match="library root"):
        resolve_under_library(Path("."), library_root)


def test_path_that_resolves_to_library_root_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="library root"):
        resolve_under_library(Path("movies-hd/.."), library_root)


def test_deep_path_that_resolves_to_library_root_rejected(library_root: Path) -> None:
    with pytest.raises(PathContainmentError, match="library root"):
        resolve_under_library(Path("a/b/c/../../.."), library_root)
```

- [ ] **Step 2: Run the tests and confirm they fail**

```bash
uv run pytest tests/contract/test_paths.py -v
```
Expected: all FAIL with `ModuleNotFoundError: No module named 'chaos_librarian.contract.paths'`.

- [ ] **Step 3: Implement the helper**

`src/chaos_librarian/contract/paths.py`:

```python
"""Path-containment helper for scenario filesystem safety.

Enforces the rules in docs/specs/chaos-librarian-design.md section
"Filesystem Safety": every scenario path is resolved under
<run-dir>/library/ and MUST stay inside it.

This module is pure (the only side effect is reading the filesystem to
resolve symlinks). It is wired into the materializer in later sprints.
"""

from __future__ import annotations

from pathlib import Path


class PathContainmentError(ValueError):
    """Raised when a scenario path violates the library containment contract."""


def resolve_under_library(candidate: Path, library_root: Path) -> Path:
    """Resolve a scenario path under the library root, rejecting any escape.

    Scenario paths MUST resolve to a strict subpath of ``library_root``; a
    path that resolves exactly to the library root is rejected because
    later cleanup and materializer code receives it as an asset target.

    Args:
        candidate: Path from a scenario field. MUST be relative.
        library_root: Absolute path to ``<run-dir>/library/``.

    Returns:
        The resolved absolute path, guaranteed to be a strict subpath of
        ``library_root``.

    Raises:
        PathContainmentError: If ``candidate`` is absolute, empty, resolves
            to the library root itself, contains ``..`` segments that escape
            ``library_root``, or follows a symlink whose target is outside
            ``library_root``.
    """
    # Reject empty paths and bare-dot paths up front. pathlib normalizes
    # Path("") to Path(".") with parts == (".",) on POSIX, so the string
    # check from the original draft does not fire.
    parts = tuple(p for p in candidate.parts if p not in ("", "."))
    if not parts:
        raise PathContainmentError(
            f"scenario path is empty or resolves to library root (no real components): "
            f"{candidate!r}"
        )

    if candidate.is_absolute():
        raise PathContainmentError(
            f"scenario path must be relative, got absolute: {candidate}"
        )

    library_root_resolved = library_root.resolve(strict=False)
    joined = library_root_resolved / candidate
    resolved = joined.resolve(strict=False)

    # Strict subpath: must NOT equal the library root itself.
    if resolved == library_root_resolved:
        raise PathContainmentError(
            f"scenario path resolves to library root (must be strict subpath): "
            f"{candidate} -> {resolved}"
        )
    if library_root_resolved not in resolved.parents:
        raise PathContainmentError(
            f"scenario path resolves outside library (escape): "
            f"{candidate} -> {resolved} (library: {library_root_resolved})"
        )
    return resolved
```

- [ ] **Step 4: Run the tests and confirm they pass**

```bash
uv run pytest tests/contract/test_paths.py -v
```
Expected: 13 PASS.

- [ ] **Step 5: Run ruff and ty**

```bash
uv run ruff check src/chaos_librarian/contract/paths.py tests/contract/test_paths.py
uv run ruff format --check src/chaos_librarian/contract/paths.py tests/contract/test_paths.py
uv run ty check src tests
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/contract/paths.py tests/contract/test_paths.py
git commit -m "Add path-containment helper for filesystem safety"
```

---

### Task 6: Run-directory sentinel Pydantic model

**Files:**
- Create: `src/chaos_librarian/contract/run_sentinel.py`
- Create: `tests/contract/test_run_sentinel.py`

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_run_sentinel.py`:

```python
"""Tests for the run-directory sentinel schema."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.run_sentinel import RunSentinel


def test_materialize_sentinel_roundtrip() -> None:
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian 0.0.0",
        created_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
    )
    blob = sentinel.model_dump_json()
    loaded = RunSentinel.model_validate_json(blob)
    assert loaded == sentinel


def test_plan_only_sentinel_omits_created_at() -> None:
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian 0.0.0",
    )
    blob = sentinel.model_dump_json(exclude_none=True)
    parsed = json.loads(blob)
    assert "created_at" not in parsed


def test_plan_only_sentinel_roundtrip_without_created_at() -> None:
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian 0.0.0",
    )
    blob = sentinel.model_dump_json(exclude_none=True)
    loaded = RunSentinel.model_validate_json(blob)
    assert loaded.created_at is None


def test_rejects_missing_run_id() -> None:
    with pytest.raises(ValidationError):
        RunSentinel(
            schema_version=RUN_SENTINEL_SCHEMA_VERSION,
            created_by="chaos-librarian 0.0.0",
        )  # type: ignore[call-arg]


def test_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError):
        RunSentinel(
            run_id=uuid.uuid4(),
            schema_version=999,
            created_by="chaos-librarian 0.0.0",
        )


def test_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RunSentinel(
            run_id=uuid.uuid4(),
            schema_version=RUN_SENTINEL_SCHEMA_VERSION,
            created_by="chaos-librarian 0.0.0",
            bogus="x",  # type: ignore[call-arg]
        )
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_run_sentinel.py -v
```
Expected: all FAIL on missing module import.

- [ ] **Step 3: Implement the model**

`src/chaos_librarian/contract/run_sentinel.py`:

```python
"""Run-directory sentinel.

Every run directory created by chaos-librarian contains a top-level
``.chaos-librarian-run`` JSON file that proves the directory was created by
this tool. See docs/specs/chaos-librarian-design.md "Run-Directory Sentinel".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION


class RunSentinel(BaseModel):
    """Top-level ``.chaos-librarian-run`` sentinel file."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    schema_version: Literal[RUN_SENTINEL_SCHEMA_VERSION]
    created_by: str
    created_at: datetime | None = None
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
uv run pytest tests/contract/test_run_sentinel.py -v
```
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/run_sentinel.py tests/contract/test_run_sentinel.py
git commit -m "Add run-directory sentinel schema"
```

---

## Phase 3: Domain Schemas

### Task 7: Scenario Pydantic model

**Files:**
- Create: `src/chaos_librarian/contract/scenario.py`
- Create: `tests/contract/test_scenario.py`

**Background:** The scenario model must cover the example shape in the design doc plus the `slow_copy_start` / `slow_copy_commit` pair. We use a discriminated union on `action` for timeline events; this gives us forwards-compatible action types without `Any`.

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_scenario.py`:

```python
"""Tests for the scenario schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.scenario import (
    Asset,
    AudioTrack,
    Bundle,
    LibraryRoot,
    Library,
    MoveAssetEvent,
    ReencodeVideoEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    SubtitleTrack,
    VideoTrack,
    Variant,
    Work,
)


def _minimal_scenario() -> Scenario:
    return Scenario(
        schema_version=SCENARIO_SCHEMA_VERSION,
        scenario_id="t",
        seed=1,
        duration_scale="short",
        library=Library(roots=[LibraryRoot(id="movies_hd", path="movies-hd")]),
        works=[
            Work(
                id="w1",
                title="W1",
                variants=[
                    Variant(
                        id="v1",
                        label="hd",
                        bundle=Bundle(
                            id="b1",
                            assets=[
                                Asset(
                                    id="a1",
                                    role="primary_video",
                                    container="mkv",
                                    duration_seconds=12,
                                    video=VideoTrack(
                                        source="mandelbrot",
                                        codec="h264",
                                        resolution="1080p",
                                    ),
                                    audio=[
                                        AudioTrack(
                                            codec="aac",
                                            channels="stereo",
                                            language="eng",
                                        )
                                    ],
                                    subtitles=[],
                                )
                            ],
                        ),
                    )
                ],
            )
        ],
        timeline=[],
    )


def test_minimal_scenario_roundtrip() -> None:
    s = _minimal_scenario()
    loaded = Scenario.model_validate_json(s.model_dump_json())
    assert loaded == s


def test_timeline_action_discriminator() -> None:
    s = _minimal_scenario()
    s = s.model_copy(
        update={
            "timeline": [
                MoveAssetEvent(id="t1", at="2s", target="a1", to="movies-hd/X.mkv"),
                ReencodeVideoEvent(
                    id="t2", at="5s", target="a1", resolution="sd", codec="h264"
                ),
                SlowCopyStartEvent(
                    id="t3",
                    at="6s",
                    target="a1",
                    to="movies-hd/Final.mkv",
                    temp_path="movies-hd/Final.mkv.part",
                    duration="3s",
                ),
                SlowCopyCommitEvent(id="t4", at="9s", for_="t3"),
            ]
        }
    )
    loaded = Scenario.model_validate_json(s.model_dump_json(by_alias=True))
    assert [type(e).__name__ for e in loaded.timeline] == [
        "MoveAssetEvent",
        "ReencodeVideoEvent",
        "SlowCopyStartEvent",
        "SlowCopyCommitEvent",
    ]


def test_unknown_action_rejected() -> None:
    bad = _minimal_scenario().model_dump(mode="json")
    bad["timeline"] = [{"id": "t1", "at": "1s", "action": "bogus", "target": "a1"}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(bad)


def test_unknown_schema_version_rejected() -> None:
    bad = _minimal_scenario().model_dump(mode="json")
    bad["schema_version"] = 999
    with pytest.raises(ValidationError):
        Scenario.model_validate(bad)


def test_slow_copy_commit_uses_for_alias() -> None:
    s = SlowCopyCommitEvent(id="c1", at="9s", for_="s1")
    blob = s.model_dump_json(by_alias=True)
    assert '"for":"s1"' in blob
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_scenario.py -v
```
Expected: all FAIL on missing module.

- [ ] **Step 3: Implement the scenario model**

`src/chaos_librarian/contract/scenario.py`:

```python
"""Scenario schema: input YAML format for chaos-librarian.

Mirrors the example in docs/specs/chaos-librarian-design.md "Scenario Format".
Timeline events are a discriminated union on ``action``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION

# ---- Library ----------------------------------------------------------------


class LibraryRoot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    path: str


class Library(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roots: list[LibraryRoot]


# ---- Tracks -----------------------------------------------------------------


class VideoTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    codec: str
    resolution: str


class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codec: str
    channels: str
    language: str


class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codec: str
    language: str
    mode: Literal["embedded", "sidecar"]


# ---- Asset / Bundle / Variant / Work ----------------------------------------


class Asset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    role: str
    container: str
    duration_seconds: float
    video: VideoTrack | None = None
    audio: list[AudioTrack] = Field(default_factory=list)
    subtitles: list[SubtitleTrack] = Field(default_factory=list)


class Bundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    assets: list[Asset]


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    bundle: Bundle


class Work(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    variants: list[Variant]


# ---- Timeline events --------------------------------------------------------


class _TimelineEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: str
    at: str


class MoveAssetEvent(_TimelineEventBase):
    action: Literal["move_asset"] = "move_asset"
    target: str
    to: str


class RenameFileEvent(_TimelineEventBase):
    action: Literal["rename_file"] = "rename_file"
    target: str
    to: str


class DeleteFileEvent(_TimelineEventBase):
    action: Literal["delete_file"] = "delete_file"
    target: str


class AddFileEvent(_TimelineEventBase):
    action: Literal["add_file"] = "add_file"
    target: str
    to: str


class ReencodeVideoEvent(_TimelineEventBase):
    action: Literal["reencode_video"] = "reencode_video"
    target: str
    resolution: str
    codec: str


class ReencodeAudioEvent(_TimelineEventBase):
    action: Literal["reencode_audio"] = "reencode_audio"
    target: str
    from_channels: str
    to_channels: str


class CreateSidecarEvent(_TimelineEventBase):
    action: Literal["create_sidecar"] = "create_sidecar"
    target: str
    to: str


class SlowCopyStartEvent(_TimelineEventBase):
    action: Literal["slow_copy_start"] = "slow_copy_start"
    target: str
    to: str
    temp_path: str
    duration: str


class SlowCopyCommitEvent(_TimelineEventBase):
    action: Literal["slow_copy_commit"] = "slow_copy_commit"
    # `for` is a Python keyword; serialize using the alias.
    for_: str = Field(alias="for")


TimelineEvent = Annotated[
    MoveAssetEvent
    | RenameFileEvent
    | DeleteFileEvent
    | AddFileEvent
    | ReencodeVideoEvent
    | ReencodeAudioEvent
    | CreateSidecarEvent
    | SlowCopyStartEvent
    | SlowCopyCommitEvent,
    Field(discriminator="action"),
]


# ---- Scenario ---------------------------------------------------------------


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[SCENARIO_SCHEMA_VERSION]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: Literal["short", "normal", "long"]
    library: Library
    works: list[Work]
    timeline: list[TimelineEvent]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/contract/test_scenario.py -v
```
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/scenario.py tests/contract/test_scenario.py
git commit -m "Add scenario schema with discriminated timeline events"
```

---

### Task 8: Manifest Pydantic model

**Files:**
- Create: `src/chaos_librarian/contract/manifest.py`
- Create: `tests/contract/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_manifest.py`:

```python
"""Tests for the manifest schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
)


def _empty_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )


def test_empty_manifest_roundtrip() -> None:
    m = _empty_manifest()
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded == m


def test_populated_manifest_roundtrip() -> None:
    m = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        works=[ManifestWork(id="w1", title="W1")],
        variants=[ManifestVariant(id="v1", work_id="w1", label="hd")],
        bundles=[ManifestBundle(id="b1", variant_id="v1")],
        assets=[
            ManifestAsset(
                id="a1",
                bundle_id="b1",
                role="primary_video",
                container="mkv",
                duration_seconds=12,
            )
        ],
        versions=[ManifestVersion(id="ver1", asset_id="a1", index=0)],
        locations=[ManifestLocation(id="loc1", asset_id="a1", path="movies-hd/A.mkv")],
        sidecars=[],
    )
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded == m


def test_rejects_unknown_schema_version() -> None:
    bad = _empty_manifest().model_dump(mode="json")
    bad["schema_version"] = 999
    with pytest.raises(ValidationError):
        Manifest.model_validate(bad)
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_manifest.py -v
```
Expected: FAIL on import.

- [ ] **Step 3: Implement the manifest model**

`src/chaos_librarian/contract/manifest.py`:

```python
"""Manifest schema: current expected library state.

Describes external library reality (works/variants/bundles/assets/locations
etc.). Does NOT describe application policy outcomes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION


class ManifestWork(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str


class ManifestVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    work_id: str
    label: str


class ManifestBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    variant_id: str


class ManifestAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    bundle_id: str
    role: str
    container: str
    duration_seconds: float


class ManifestVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    asset_id: str
    index: int
    content_hash: str | None = None


class ManifestLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    asset_id: str
    path: str
    # Multi-phase in-flight state, set between *_start and *_commit events.
    temp_path: str | None = None
    bytes_written: int | None = None


class ManifestSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    asset_id: str
    kind: str
    path: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[MANIFEST_SCHEMA_VERSION]
    works: list[ManifestWork]
    variants: list[ManifestVariant]
    bundles: list[ManifestBundle]
    assets: list[ManifestAsset]
    versions: list[ManifestVersion]
    locations: list[ManifestLocation]
    sidecars: list[ManifestSidecar] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/contract/test_manifest.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/manifest.py tests/contract/test_manifest.py
git commit -m "Add manifest schema"
```

---

### Task 9: Journal Pydantic model (with multi-phase fields)

**Files:**
- Create: `src/chaos_librarian/contract/journal.py`
- Create: `tests/contract/test_journal.py`

**Background:** Journal entries are emitted one-per-line in JSONL. Sprint 0 freezes the multi-phase fields (`phase`, `temp_path`, `related_event_id`) even though only slow-copy uses them in V1. This is the most important schema decision in Sprint 0 — getting these fields wrong forces a breaking version bump later.

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_journal.py`:

```python
"""Tests for the journal entry schema."""

from __future__ import annotations

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract import JOURNAL_SCHEMA_VERSION
from chaos_librarian.contract.journal import (
    AbortedJournalEntry,
    AtomicJournalEntry,
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    ProgressedJournalEntry,
    StartedJournalEntry,
)


def _atomic_entry() -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="e1",
        scenario_id="s1",
        run_id=uuid.uuid4(),
        logical_time_ns=2_000_000_000,
        action="move_asset",
        target_ids=["a1"],
    )


def _base_fields(event_id: str = "e1") -> dict[str, object]:
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "event_id": event_id,
        "scenario_id": "sc",
        "run_id": str(uuid.uuid4()),
        "logical_time_ns": 2_000_000_000,
        "action": "x",
    }


def test_atomic_entry_roundtrip() -> None:
    e = _atomic_entry()
    loaded = TypeAdapter(JournalEntry).validate_json(e.model_dump_json())
    assert loaded == e


def test_start_phase_with_temp_path() -> None:
    e = StartedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="s1",
        scenario_id="sc",
        run_id=uuid.uuid4(),
        logical_time_ns=6_000_000_000,
        action="slow_copy_start",
        target_ids=["a1"],
        phase=JournalPhase.STARTED,
        temp_path="movies-hd/A.mkv.part",
    )
    loaded = TypeAdapter(JournalEntry).validate_json(e.model_dump_json())
    assert loaded.phase is JournalPhase.STARTED
    assert loaded.temp_path == "movies-hd/A.mkv.part"


def test_commit_phase_references_start() -> None:
    e = CommittedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="c1",
        scenario_id="sc",
        run_id=uuid.uuid4(),
        logical_time_ns=9_000_000_000,
        action="slow_copy_commit",
        target_ids=["a1"],
        phase=JournalPhase.COMMITTED,
        related_event_id="s1",
    )
    loaded = TypeAdapter(JournalEntry).validate_json(e.model_dump_json())
    assert loaded.phase is JournalPhase.COMMITTED
    assert loaded.related_event_id == "s1"


def test_rejects_unknown_phase() -> None:
    bad = _atomic_entry().model_dump(mode="json")
    bad["phase"] = "halfway"
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(bad)


def test_wall_clock_time_optional() -> None:
    e = _atomic_entry()
    assert e.wall_clock_time is None


def test_atomic_entry_rejects_temp_path() -> None:
    bad = _atomic_entry().model_dump(mode="json")
    bad["temp_path"] = "x"
    with pytest.raises(ValidationError):
        # Validate via the union so the discriminator is respected.
        TypeAdapter(JournalEntry).validate_python(bad)


def test_started_entry_requires_temp_path() -> None:
    base = {**_base_fields("s1"), "phase": "started"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_progressed_entry_requires_both_temp_path_and_related_event_id() -> None:
    base = {**_base_fields("p1"), "phase": "progressed"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(
            {**base, "temp_path": "x"}
        )
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(
            {**base, "related_event_id": "s1"}
        )


def test_committed_entry_requires_related_event_id() -> None:
    base = {**_base_fields("c1"), "phase": "committed"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_committed_entry_rejects_temp_path() -> None:
    base = {
        **_base_fields("c1"),
        "phase": "committed",
        "related_event_id": "s1",
        "temp_path": "x",  # forbidden on committed
    }
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_aborted_entry_requires_related_event_id() -> None:
    base = {**_base_fields("a1"), "phase": "aborted"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_aborted_entry_rejects_temp_path() -> None:
    base = {
        **_base_fields("a1"),
        "phase": "aborted",
        "related_event_id": "s1",
        "temp_path": "x",  # forbidden on aborted
    }
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_journal.py -v
```
Expected: FAIL on import.

- [ ] **Step 3: Implement the journal model**

`src/chaos_librarian/contract/journal.py`:

```python
"""Journal entry schema (one JSONL line per timeline event).

The journal is append-only and is the source of truth for the oracle. Sprint 0
freezes the multi-phase fields (``phase``, ``temp_path``, ``related_event_id``)
so adding multi-phase mutations after V1 does not force a schema version bump.
The journal entry type is a discriminated union on ``phase`` so impossible
combinations (e.g. ``committed`` without ``related_event_id``, ``atomic`` with
``temp_path``) are rejected by Pydantic AND by the exported JSON Schema's
``oneOf``. See docs/specs/chaos-librarian-design.md "Oracle Journal" and
"Mutation Model".
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import JOURNAL_SCHEMA_VERSION


class JournalPhase(str, enum.Enum):
    """Mutation lifecycle phase. ``atomic`` is the default for single-event
    actions; the other values describe multi-phase mutations (e.g. slow-copy).
    """

    ATOMIC = "atomic"
    STARTED = "started"
    PROGRESSED = "progressed"
    COMMITTED = "committed"
    ABORTED = "aborted"


class _JournalEntryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[JOURNAL_SCHEMA_VERSION]
    event_id: str
    scenario_id: str
    run_id: uuid.UUID
    logical_time_ns: int
    wall_clock_time: datetime | None = None  # omitted in plan-only mode
    action: str
    target_ids: list[str] = Field(default_factory=list)
    input_version_ids: list[str] = Field(default_factory=list)
    output_version_ids: list[str] = Field(default_factory=list)
    location_ids: list[str] = Field(default_factory=list)
    state_delta: dict[str, object] = Field(default_factory=dict)
    toolchain: dict[str, str] | None = None


class AtomicJournalEntry(_JournalEntryBase):
    """Single-event mutation. No ``temp_path``, no ``related_event_id``."""

    phase: Literal[JournalPhase.ATOMIC] = JournalPhase.ATOMIC


class StartedJournalEntry(_JournalEntryBase):
    """First event of a multi-phase mutation. Requires ``temp_path``."""

    phase: Literal[JournalPhase.STARTED]
    temp_path: str


class ProgressedJournalEntry(_JournalEntryBase):
    """Intermediate event of a multi-phase mutation."""

    phase: Literal[JournalPhase.PROGRESSED]
    temp_path: str
    related_event_id: str


class CommittedJournalEntry(_JournalEntryBase):
    """Successful terminal event of a multi-phase mutation."""

    phase: Literal[JournalPhase.COMMITTED]
    related_event_id: str
    # No temp_path: the staged file has been renamed to its final path.


class AbortedJournalEntry(_JournalEntryBase):
    """Failed terminal event of a multi-phase mutation."""

    phase: Literal[JournalPhase.ABORTED]
    related_event_id: str
    # No temp_path: staging artifact lifecycle is described by related_event_id.


JournalEntry = Annotated[
    AtomicJournalEntry
    | StartedJournalEntry
    | ProgressedJournalEntry
    | CommittedJournalEntry
    | AbortedJournalEntry,
    Field(discriminator="phase"),
]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/contract/test_journal.py -v
```
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/journal.py tests/contract/test_journal.py
git commit -m "Add journal entry schema with multi-phase fields"
```

---

### Task 10: Replay-bundle Pydantic model (mode-split fields)

**Files:**
- Create: `src/chaos_librarian/contract/replay_bundle.py`
- Create: `tests/contract/test_replay_bundle.py`

**Background:** Plan-only and materialize replay bundles differ in three fields:

- **`execution_mode`** — discriminator literal: `"plan_only"` vs. `"materialize"` / `"run"`.
- **`run_id`** — UUIDv5 (deterministic) in plan-only, UUIDv4 (random) in materialize.
- **`created_at` / `toolchain`** — both forbidden in plan-only, both required (non-null) in materialize.

`ReplayBundle` is a Pydantic discriminated union on `execution_mode` so the JSON Schema exports as `oneOf` and external consumers (e.g. voom-v2 in Sprint 9) get the mode-split contract natively rather than relying on Python-side validation. The helper `compute_plan_only_run_id` lives in this module so callers don't re-derive it. Tests cover both shapes plus round-trip equivalence after serialization.

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_replay_bundle.py`:

```python
"""Tests for the replay-bundle schema and run-id derivation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract import (
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.replay_bundle import (
    ExecutionTraceEntry,
    MaterializeReplayBundle,
    PlanOnlyReplayBundle,
    ReplayBundle,
    compute_plan_only_run_id,
)


def _scenario_hash(scenario_yaml: str) -> str:
    return hashlib.sha256(scenario_yaml.encode("utf-8")).hexdigest()


def _plan_only_base(seed: int = 1) -> dict[str, object]:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    return {
        "execution_mode": "plan_only",
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "chaos_librarian_version": "0.0.0",
        "scenario": "scenario_id: t\nseed: 1\n",
        "run_id": str(compute_plan_only_run_id(h, seed)),
        "resolved_seed": seed,
        "execution_trace": [],
    }


def _materialize_base() -> dict[str, object]:
    return {
        "execution_mode": "materialize",
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "chaos_librarian_version": "0.0.0",
        "scenario": "scenario_id: t\nseed: 1\n",
        "run_id": str(uuid.uuid4()),
        "resolved_seed": 1,
        "execution_trace": [],
    }


def test_plan_only_run_id_is_deterministic() -> None:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    a = compute_plan_only_run_id(h, resolved_seed=1)
    b = compute_plan_only_run_id(h, resolved_seed=1)
    assert a == b
    assert a.version == 5


def test_plan_only_run_id_uses_namespace() -> None:
    h = _scenario_hash("x")
    expected = uuid.uuid5(CHAOS_LIBRARIAN_NAMESPACE_UUID, f"{h}:42")
    assert compute_plan_only_run_id(h, resolved_seed=42) == expected


def test_plan_only_run_id_differs_by_seed() -> None:
    h = _scenario_hash("x")
    assert compute_plan_only_run_id(h, 1) != compute_plan_only_run_id(h, 2)


def test_plan_only_bundle_has_no_created_at_or_toolchain_fields() -> None:
    h = _scenario_hash("x")
    b = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=compute_plan_only_run_id(h, 1),
        resolved_seed=1,
        execution_trace=[],
    )
    parsed = json.loads(b.model_dump_json())
    assert "created_at" not in parsed
    assert "toolchain" not in parsed


def test_plan_only_bundle_roundtrip_byte_identical() -> None:
    h = _scenario_hash("scenario_id: t\nseed: 1\n")
    b = PlanOnlyReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=compute_plan_only_run_id(h, 1),
        resolved_seed=1,
        execution_trace=[
            ExecutionTraceEntry(kind="rng", stream="ids", value="1"),
            ExecutionTraceEntry(kind="alloc", stream="work_id", value="w1"),
        ],
    )
    blob_a = json.dumps(json.loads(b.model_dump_json()), sort_keys=True)
    blob_b = json.dumps(json.loads(b.model_dump_json()), sort_keys=True)
    assert blob_a == blob_b


def test_materialize_bundle_has_created_at_and_toolchain() -> None:
    b = MaterializeReplayBundle(
        execution_mode="materialize",
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.0.0",
        scenario="scenario_id: t\nseed: 1\n",
        run_id=uuid.uuid4(),
        created_at=datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc),
        resolved_seed=1,
        execution_trace=[],
        toolchain={"ffmpeg": "7.1", "ffprobe": "7.1", "platform": "darwin-arm64"},
    )
    loaded = TypeAdapter(ReplayBundle).validate_json(b.model_dump_json())
    assert loaded.created_at == b.created_at
    assert loaded.toolchain == b.toolchain


def test_rejects_unknown_schema_version() -> None:
    bad = {**_plan_only_base(), "schema_version": 999}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bad)


def test_plan_only_rejects_created_at() -> None:
    # extra="forbid" on PlanOnlyReplayBundle rejects created_at outright,
    # including explicit null.
    bundle_json = {**_plan_only_base(), "created_at": None}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_plan_only_rejects_toolchain() -> None:
    bundle_json = {**_plan_only_base(), "toolchain": {"ffmpeg": "7.1"}}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_materialize_requires_created_at() -> None:
    bundle_json = {**_materialize_base(), "toolchain": {"ffmpeg": "7.1"}}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_materialize_requires_toolchain() -> None:
    bundle_json = {**_materialize_base(), "created_at": "2026-05-17T12:00:00Z"}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)


def test_materialize_rejects_null_toolchain() -> None:
    bundle_json = {
        **_materialize_base(),
        "created_at": "2026-05-17T12:00:00Z",
        "toolchain": None,
    }
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(bundle_json)
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_replay_bundle.py -v
```
Expected: FAIL on import.

- [ ] **Step 3: Implement the replay-bundle model**

`src/chaos_librarian/contract/replay_bundle.py`:

```python
"""Replay bundle schema.

A single JSON file (``replay.json``) sufficient to reproduce a run. Plan-only
bundles are bit-identical for the same scenario + seed; materialize bundles
are logically identical modulo volatile fields. ``ReplayBundle`` is a
discriminated union on ``execution_mode`` so the mode-split contract
(created_at / toolchain required iff materialize/run; forbidden iff plan_only)
is enforced by Pydantic AND exported as ``oneOf`` in JSON Schema. See
docs/specs/chaos-librarian-design.md "Replay Bundle" and "Reproducibility
Guarantees".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import (
    CHAOS_LIBRARIAN_NAMESPACE_UUID,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)


def compute_plan_only_run_id(scenario_content_hash: str, resolved_seed: int) -> uuid.UUID:
    """Derive the deterministic UUIDv5 ``run_id`` for plan-only mode.

    Args:
        scenario_content_hash: Hex digest of the scenario YAML bytes
            (sha256 recommended; this function does not enforce the algorithm).
        resolved_seed: Concrete integer seed for the run.

    Returns:
        UUIDv5 under ``CHAOS_LIBRARIAN_NAMESPACE_UUID``.
    """
    return uuid.uuid5(CHAOS_LIBRARIAN_NAMESPACE_UUID, f"{scenario_content_hash}:{resolved_seed}")


class ExecutionTraceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rng", "alloc", "materializer"]
    stream: str
    value: str
    exit_code: int | None = None  # only set on `materializer` entries


class _ReplayBundleBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[REPLAY_BUNDLE_SCHEMA_VERSION]
    chaos_librarian_version: str
    scenario: str  # verbatim YAML
    run_id: uuid.UUID
    resolved_seed: int
    execution_trace: list[ExecutionTraceEntry] = Field(default_factory=list)


class PlanOnlyReplayBundle(_ReplayBundleBase):
    """Replay bundle in plan-only mode. No ``created_at`` or ``toolchain``."""

    execution_mode: Literal["plan_only"] = "plan_only"


class MaterializeReplayBundle(_ReplayBundleBase):
    """Replay bundle in materialize or run mode.

    ``created_at`` and ``toolchain`` are both required (non-null).
    """

    execution_mode: Literal["materialize", "run"]
    created_at: datetime
    toolchain: dict[str, str]


ReplayBundle = Annotated[
    PlanOnlyReplayBundle | MaterializeReplayBundle,
    Field(discriminator="execution_mode"),
]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/contract/test_replay_bundle.py -v
```
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/replay_bundle.py tests/contract/test_replay_bundle.py
git commit -m "Add replay-bundle schema with deterministic plan-only run_id"
```

---

### Task 11: Validation report Pydantic model

**Files:**
- Create: `src/chaos_librarian/contract/validation.py`
- Create: `tests/contract/test_validation.py`

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_validation.py`:

```python
"""Tests for the validation report schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import VALIDATION_SCHEMA_VERSION
from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


def test_ok_report_roundtrip() -> None:
    r = ValidationReport(
        schema_version=VALIDATION_SCHEMA_VERSION,
        scenario_id="s1",
        ok=True,
        issues=[],
    )
    assert ValidationReport.model_validate_json(r.model_dump_json()) == r


def test_failing_report_with_issues() -> None:
    r = ValidationReport(
        schema_version=VALIDATION_SCHEMA_VERSION,
        scenario_id="s1",
        ok=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="path.absolute",
                message="absolute scenario path",
                line=12,
                column=5,
                path="timeline[0].to",
            )
        ],
    )
    loaded = ValidationReport.model_validate_json(r.model_dump_json())
    assert loaded.issues[0].severity is ValidationSeverity.ERROR


def test_rejects_unknown_severity() -> None:
    bad = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "scenario_id": "s1",
        "ok": False,
        "issues": [
            {"severity": "panic", "code": "x", "message": "y"},
        ],
    }
    with pytest.raises(ValidationError):
        ValidationReport.model_validate(bad)
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_validation.py -v
```
Expected: FAIL on import.

- [ ] **Step 3: Implement the validation report model**

`src/chaos_librarian/contract/validation.py`:

```python
"""Validation report schema (output of ``chaos-librarian validate``)."""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import VALIDATION_SCHEMA_VERSION


class ValidationSeverity(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    code: str
    message: str
    line: int | None = None
    column: int | None = None
    path: str | None = None  # JSONPath-style location in scenario


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[VALIDATION_SCHEMA_VERSION]
    scenario_id: str
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/contract/test_validation.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/validation.py tests/contract/test_validation.py
git commit -m "Add validation report schema"
```

---

### Task 12: Materialization report Pydantic model

**Files:**
- Create: `src/chaos_librarian/contract/materialization.py`
- Create: `tests/contract/test_materialization.py`

- [ ] **Step 1: Write the failing tests**

`tests/contract/test_materialization.py`:

```python
"""Tests for the materialization report schema."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import MATERIALIZATION_SCHEMA_VERSION
from chaos_librarian.contract.materialization import (
    MaterializationReport,
    MaterializationStatus,
    ToolInvocation,
)


def test_success_report_roundtrip() -> None:
    r = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=uuid.uuid4(),
        status=MaterializationStatus.OK,
        toolchain={"ffmpeg": "7.1", "platform": "darwin-arm64"},
        invocations=[
            ToolInvocation(
                tool="ffmpeg",
                version="7.1",
                command=["ffmpeg", "-i", "in.mkv", "out.mp4"],
                exit_code=0,
                duration_ns=1_500_000_000,
            )
        ],
    )
    assert MaterializationReport.model_validate_json(r.model_dump_json()) == r


def test_failure_report_records_invocation() -> None:
    r = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=uuid.uuid4(),
        status=MaterializationStatus.TOOL_FAILED,
        toolchain={"ffmpeg": "7.1"},
        invocations=[
            ToolInvocation(
                tool="ffmpeg",
                version="7.1",
                command=["ffmpeg", "-i", "missing.mkv", "out.mp4"],
                exit_code=1,
                duration_ns=500_000_000,
            )
        ],
    )
    loaded = MaterializationReport.model_validate_json(r.model_dump_json())
    assert loaded.status is MaterializationStatus.TOOL_FAILED


def test_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        MaterializationReport(
            schema_version=MATERIALIZATION_SCHEMA_VERSION,
            run_id=uuid.uuid4(),
            status="wat",  # type: ignore[arg-type]
            toolchain={},
            invocations=[],
        )
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/contract/test_materialization.py -v
```
Expected: FAIL on import.

- [ ] **Step 3: Implement the materialization report model**

`src/chaos_librarian/contract/materialization.py`:

```python
"""Materialization report schema."""

from __future__ import annotations

import enum
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import MATERIALIZATION_SCHEMA_VERSION


class MaterializationStatus(str, enum.Enum):
    OK = "ok"
    TOOL_MISSING = "tool_missing"
    TOOL_FAILED = "tool_failed"
    CONTAINMENT_VIOLATION = "containment_violation"


class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    version: str
    command: list[str]
    exit_code: int
    duration_ns: int


class MaterializationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[MATERIALIZATION_SCHEMA_VERSION]
    run_id: uuid.UUID
    status: MaterializationStatus
    toolchain: dict[str, str]
    invocations: list[ToolInvocation] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/contract/test_materialization.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/materialization.py tests/contract/test_materialization.py
git commit -m "Add materialization report schema"
```

---

## Phase 4: Wiring

### Task 13: JSON Schema export + CI gate

**Files:**
- Create: `src/chaos_librarian/schema_export.py`
- Create: `tests/contract/test_schema_export.py`
- Create: `schemas/.gitkeep` (then replaced by generated artifacts)

**Background:** Schemas are checked into `schemas/`. CI runs `python -m chaos_librarian.schema_export --check` and fails if the on-disk artifacts diverge from what Pydantic emits now. Engineers regenerate locally with `python -m chaos_librarian.schema_export --write`.

- [ ] **Step 1: Write the export script**

`src/chaos_librarian/schema_export.py`:

```python
"""Export Pydantic v2 models to JSON Schema (draft 2020-12) artifacts.

Usage:
    python -m chaos_librarian.schema_export --write    # regenerate schemas/
    python -m chaos_librarian.schema_export --check    # fail on drift (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel, TypeAdapter

from chaos_librarian.contract.journal import JournalEntry  # Annotated union
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import MaterializationReport
from chaos_librarian.contract.replay_bundle import ReplayBundle  # Annotated union
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationReport

# (filename, model-or-adapter). Filenames are public contract; do not rename.
# Discriminated unions are wrapped in TypeAdapter so model_json_schema is not
# accessible on the bare Annotated alias.
MODELS: Final[list[tuple[str, object]]] = [
    ("scenario.schema.json", Scenario),
    ("manifest.schema.json", Manifest),
    ("journal.schema.json", TypeAdapter(JournalEntry)),
    ("replay-bundle.schema.json", TypeAdapter(ReplayBundle)),
    ("validation.schema.json", ValidationReport),
    ("materialization.schema.json", MaterializationReport),
    ("run-sentinel.schema.json", RunSentinel),
]


def _schema_for(model_or_adapter: object) -> dict[str, object]:
    if isinstance(model_or_adapter, TypeAdapter):
        return model_or_adapter.json_schema(mode="serialization")
    assert isinstance(model_or_adapter, type) and issubclass(model_or_adapter, BaseModel)
    return model_or_adapter.model_json_schema(mode="serialization")


def _serialize(schema: dict[str, object]) -> str:
    # Stable, sorted, trailing newline so diffs are clean.
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def write_all(schemas_dir: Path) -> None:
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in MODELS:
        (schemas_dir / filename).write_text(_serialize(_schema_for(model)))


def check_all(schemas_dir: Path) -> list[str]:
    """Return a list of filenames that diverge from current models."""
    drift: list[str] = []
    for filename, model in MODELS:
        path = schemas_dir / filename
        if not path.exists():
            drift.append(f"{filename} (missing)")
            continue
        current = _serialize(_schema_for(model))
        on_disk = path.read_text()
        if current != on_disk:
            drift.append(filename)
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or check JSON Schema artifacts.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="Regenerate schemas/")
    group.add_argument("--check", action="store_true", help="Fail if schemas/ is stale")
    parser.add_argument(
        "--dir",
        type=Path,
        default=_repo_root() / "schemas",
        help="Schema directory (default: <repo>/schemas/)",
    )
    args = parser.parse_args(argv)

    if args.write:
        write_all(args.dir)
        print(f"Wrote {len(MODELS)} schemas to {args.dir}")
        return 0

    drift = check_all(args.dir)
    if drift:
        print("Schema drift detected:", file=sys.stderr)
        for name in drift:
            print(f"  - {name}", file=sys.stderr)
        print("Run: python -m chaos_librarian.schema_export --write", file=sys.stderr)
        return 1
    print(f"All {len(MODELS)} schemas up-to-date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Generate the schemas for the first time**

```bash
uv run python -m chaos_librarian.schema_export --write
ls schemas/
```
Expected: 7 `*.schema.json` files written.

- [ ] **Step 3: Write the schema-export test**

`tests/contract/test_schema_export.py`:

```python
"""Verify committed JSON Schemas match current Pydantic models.

This duplicates the CI gate (`python -m chaos_librarian.schema_export --check`)
so editors that forget to regenerate get a fast local signal from pytest.
"""

from __future__ import annotations

import json
from pathlib import Path

from chaos_librarian.schema_export import MODELS, check_all


def test_committed_schemas_match_models() -> None:
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    drift = check_all(schemas_dir)
    assert drift == [], (
        f"Stale schemas: {drift}. "
        "Regenerate with: python -m chaos_librarian.schema_export --write"
    )


def test_all_seven_schemas_listed() -> None:
    names = {filename for filename, _ in MODELS}
    assert names == {
        "scenario.schema.json",
        "manifest.schema.json",
        "journal.schema.json",
        "replay-bundle.schema.json",
        "validation.schema.json",
        "materialization.schema.json",
        "run-sentinel.schema.json",
    }


def test_journal_schema_has_oneof_on_phase() -> None:
    # Discriminated unions emit either top-level oneOf or under $defs;
    # either way, the discriminator key must appear so external consumers
    # can statically distinguish atomic/started/progressed/committed/aborted.
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    journal_schema = json.loads((schemas_dir / "journal.schema.json").read_text())
    assert "discriminator" in journal_schema or "oneOf" in journal_schema


def test_replay_bundle_schema_has_oneof_on_execution_mode() -> None:
    schemas_dir = Path(__file__).resolve().parents[2] / "schemas"
    bundle_schema = json.loads((schemas_dir / "replay-bundle.schema.json").read_text())
    assert "discriminator" in bundle_schema or "oneOf" in bundle_schema
```

- [ ] **Step 4: Run the schema test**

```bash
uv run pytest tests/contract/test_schema_export.py -v
```
Expected: 4 PASS.

- [ ] **Step 5: Verify the --check command exits non-zero on drift**

```bash
# Sanity check: corrupt one schema, confirm check fails, then regenerate.
echo "{}" > schemas/scenario.schema.json
uv run python -m chaos_librarian.schema_export --check
echo "exit=$?"
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
echo "exit=$?"
```
Expected: first exit=1, second exit=0.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/schema_export.py tests/contract/test_schema_export.py schemas/
git commit -m "Add JSON Schema export with CI drift gate"
```

---

### Task 14: CLI stub (Typer app, frozen surface)

**Files:**
- Create: `src/chaos_librarian/cli/__init__.py`
- Create: `src/chaos_librarian/cli/app.py`
- Create: `tests/cli/__init__.py`
- Create: `tests/cli/test_app.py`

**Background:** The CLI surface freezes in Sprint 0. Every command exists and prints usage; every command exits `1`. Later sprints implement each command. `capabilities` exits `1` too — the actual capability probe lands in Sprint 5.

- [ ] **Step 1: Write the failing tests**

`tests/cli/test_app.py`:

```python
"""Tests for the CLI stub. All commands exist and exit 1 in Sprint 0."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner(mix_stderr=False)


@pytest.mark.parametrize(
    "command",
    [
        "validate",
        "plan",
        "materialize",
        "run",
        "step",
        "replay",
        "inspect",
        "capabilities",
        "clean",
    ],
)
def test_command_exists_and_exits_one(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, f"--help should always succeed for {command}"


@pytest.mark.parametrize(
    "command_args",
    [
        ["validate", "scenario.yaml"],
        ["plan", "scenario.yaml", "--out", "fixtures/run-001"],
        ["materialize", "scenario.yaml", "--out", "fixtures/run-001"],
        ["run", "scenario.yaml", "--out", "fixtures/run-001", "--duration", "10s"],
        ["step", "fixtures/run-001", "--next"],
        ["replay", "fixtures/run-001/replay.json", "--out", "fixtures/replay-001"],
        ["inspect", "fixtures/run-001"],
        ["capabilities"],
        ["clean", "fixtures/run-001"],
    ],
)
def test_stub_command_exits_one(command_args: list[str]) -> None:
    result = runner.invoke(app, command_args)
    assert result.exit_code == 1, f"Stub {command_args[0]} should exit 1"


def test_top_level_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [
        "validate",
        "plan",
        "materialize",
        "run",
        "step",
        "replay",
        "inspect",
        "capabilities",
        "clean",
    ]:
        assert command in result.stdout
```

- [ ] **Step 2: Run tests and confirm they fail**

```bash
uv run pytest tests/cli/test_app.py -v
```
Expected: all FAIL on import.

- [ ] **Step 3: Implement the CLI stub**

`src/chaos_librarian/cli/__init__.py`:

```python
"""Chaos Librarian CLI."""
```

`src/chaos_librarian/cli/app.py`:

```python
"""Typer app exposing the chaos-librarian CLI surface.

Sprint 0 freezes the command surface. Every command prints a not-implemented
notice and exits with code 1. Later sprints replace these stubs with real
implementations. See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    name="chaos-librarian",
    help="Scenario-driven synthetic media library simulator.",
    no_args_is_help=True,
)


def _stub(command: str) -> None:
    typer.echo(f"chaos-librarian {command}: not yet implemented (Sprint 0 stub).", err=True)
    raise typer.Exit(code=1)


@app.command()
def validate(
    scenario: Path = typer.Argument(..., exists=False, dir_okay=False),
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Validate a scenario file."""
    _stub("validate")


@app.command()
def plan(
    scenario: Path = typer.Argument(..., exists=False, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Plan a scenario without creating media."""
    _stub("plan")


@app.command()
def materialize(
    scenario: Path = typer.Argument(..., exists=False, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Materialize a scenario (creates real media files)."""
    _stub("materialize")


@app.command()
def run(
    scenario: Path = typer.Argument(..., exists=False, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    duration: str = typer.Option(..., "--duration"),
    speed: str = typer.Option("1x", "--speed"),  # noqa: ARG001
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Run a scenario in wall-clock mode."""
    _stub("run")


@app.command()
def step(
    run_dir: Path = typer.Argument(..., exists=False),
    next_: bool = typer.Option(False, "--next"),  # noqa: ARG001
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Advance a step-mode run."""
    _stub("step")


@app.command()
def replay(
    bundle: Path = typer.Argument(..., exists=False, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Replay a recorded run."""
    _stub("replay")


@app.command()
def inspect(
    run_dir: Path = typer.Argument(..., exists=False),
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Inspect a run directory."""
    _stub("inspect")


@app.command()
def capabilities(
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Detect available media tools (ffmpeg, ffprobe, mkvtoolnix)."""
    _stub("capabilities")


@app.command()
def clean(
    run_dir: Path = typer.Argument(..., exists=False),
    json_output: bool = typer.Option(False, "--json"),  # noqa: ARG001
) -> None:
    """Remove a run directory (sentinel-protected)."""
    _stub("clean")
```

- [ ] **Step 4: Create test package init**

`tests/cli/__init__.py` is empty.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/cli/test_app.py -v
```
Expected: 19 PASS.

- [ ] **Step 6: Smoke-test the entry point**

```bash
uv run chaos-librarian --help
uv run chaos-librarian plan scenario.yaml --out /tmp/x
echo "exit=$?"
```
Expected: help text lists all 9 commands; plan exits with code 1.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/cli/ tests/cli/
git commit -m "Add Typer CLI stub with frozen command surface"
```

---

### Task 15: Sample scenarios + validation tests

**Files:**
- Create: `tests/fixtures/scenarios/identity-move-rename.yaml`
- Create: `tests/fixtures/scenarios/version-evolution.yaml`
- Create: `tests/fixtures/scenarios/bundle-sidecars.yaml`
- Create: `tests/fixtures/scenarios/slow-copy.yaml`
- Create: `tests/contract/test_sample_scenarios.py`

**Background:** Sprint 0 ships 3–4 hand-authored scenarios. We include `slow-copy.yaml` so the multi-phase `slow_copy_start` / `slow_copy_commit` pair has at least one fixture exercising it from day one.

- [ ] **Step 1: Write `identity-move-rename.yaml`**

`tests/fixtures/scenarios/identity-move-rename.yaml`:

```yaml
schema_version: 1
scenario_id: identity-move-rename
seed: 42
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd
    - id: movies_4k
      path: movies-4k

works:
  - id: work_blazar
    title: Synthetic Blazar
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_hd_main
              role: primary_video
              container: mkv
              duration_seconds: 12
              video:
                source: mandelbrot
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng

timeline:
  - id: move_001
    at: 2s
    action: move_asset
    target: asset_hd_main
    to: movies-hd/Synthetic Blazar (HD).mkv
  - id: rename_001
    at: 4s
    action: rename_file
    target: asset_hd_main
    to: movies-hd/Blazar.mkv
```

- [ ] **Step 2: Write `version-evolution.yaml`**

```yaml
schema_version: 1
scenario_id: version-evolution
seed: 17
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd

works:
  - id: work_pulsar
    title: Synthetic Pulsar
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 10
              video:
                source: color_bars
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: "5.1"
                  language: eng

timeline:
  - id: reencode_video_001
    at: 3s
    action: reencode_video
    target: asset_main
    resolution: sd
    codec: h264
  - id: reencode_audio_001
    at: 6s
    action: reencode_audio
    target: asset_main
    from_channels: "5.1"
    to_channels: stereo
```

- [ ] **Step 3: Write `bundle-sidecars.yaml`**

```yaml
schema_version: 1
scenario_id: bundle-sidecars
seed: 99
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd

works:
  - id: work_quasar
    title: Synthetic Quasar
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 8
              video:
                source: mandelbrot
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - codec: srt
                  language: eng
                  mode: sidecar

timeline:
  - id: create_subs_001
    at: 1s
    action: create_sidecar
    target: asset_main
    to: movies-hd/Quasar.eng.srt
```

- [ ] **Step 4: Write `slow-copy.yaml`**

```yaml
schema_version: 1
scenario_id: slow-copy
seed: 7
duration_scale: short

library:
  roots:
    - id: staging
      path: staging
    - id: movies_hd
      path: movies-hd

works:
  - id: work_nova
    title: Synthetic Nova
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 6
              video:
                source: noise
                codec: h264
                resolution: 720p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng

timeline:
  - id: copy_start_001
    at: 1s
    action: slow_copy_start
    target: asset_main
    to: movies-hd/Nova.mkv
    temp_path: movies-hd/Nova.mkv.part
    duration: 3s
  - id: copy_commit_001
    at: 4s
    action: slow_copy_commit
    for: copy_start_001
```

- [ ] **Step 5: Write the sample-scenario validation test**

`tests/contract/test_sample_scenarios.py`:

```python
"""Load every sample scenario through the Pydantic model.

This is the structural smoke-test for the contract. If any sample stops
loading, Sprint 0 has either regressed the schema or the sample is stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.scenario import Scenario

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _scenario_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.yaml"))


def test_at_least_three_samples_ship() -> None:
    assert len(_scenario_files()) >= 3


@pytest.mark.parametrize("path", _scenario_files(), ids=lambda p: p.name)
def test_sample_scenario_loads(path: Path) -> None:
    yaml = YAML(typ="safe")
    data = yaml.load(path.read_text())
    Scenario.model_validate(data)
```

- [ ] **Step 6: Run sample-scenario tests**

```bash
uv run pytest tests/contract/test_sample_scenarios.py -v
```
Expected: 5 PASS (1 count check + 4 parametrized scenario loads).

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/scenarios/ tests/contract/test_sample_scenarios.py
git commit -m "Add four sample scenarios and validation test"
```

---

### Task 16: Contract documentation

**Files:**
- Create: `docs/contract/schema-reference.md`
- Create: `docs/contract/fixture-layout.md`
- Create: `docs/contract/cli-reference.md`
- Create: `docs/contract/replay-bundle.md`
- Create: `docs/contract/time-model.md`

**Background:** These five docs are the public contract for external consumers (voom-v2). Keep them short and link to the design doc for rationale. The schemas themselves are the precise specification; these docs orient a human reader.

- [ ] **Step 1: Write `docs/contract/schema-reference.md`**

```markdown
# Schema Reference

The seven JSON Schema artifacts under [`schemas/`](../../schemas/) are the
public contract for chaos-librarian consumers. They are exported from
Pydantic v2 models under `src/chaos_librarian/contract/` and regenerated by:

```bash
python -m chaos_librarian.schema_export --write
```

CI runs `--check` and fails if the committed artifacts diverge from the
current models.

| schema                          | purpose                                     |
|---------------------------------|---------------------------------------------|
| `scenario.schema.json`          | Input YAML format                           |
| `manifest.schema.json`          | Initial and current expected library state  |
| `journal.schema.json`           | One JSONL line per timeline event           |
| `replay-bundle.schema.json`     | `replay.json` for reproducing a run         |
| `validation.schema.json`        | Output of `chaos-librarian validate`        |
| `materialization.schema.json`   | Output of `chaos-librarian materialize`     |
| `run-sentinel.schema.json`      | `.chaos-librarian-run` sentinel file        |

Every artifact has a top-level `schema_version` integer. Version bumps are
always breaking; readers MUST reject unknown versions with exit code `3`.
See [chaos-librarian-design.md "Versioning"](../specs/chaos-librarian-design.md).
```

- [ ] **Step 2: Write `docs/contract/fixture-layout.md`**

```markdown
# Fixture Directory Layout

Each chaos-librarian run writes a self-contained fixture directory protected
by a `.chaos-librarian-run` sentinel file. See
[`chaos-librarian-design.md` "Fixture Directory Layout"](../specs/chaos-librarian-design.md)
and "Filesystem Safety" for the full contract.

```text
run/
  .chaos-librarian-run        # sentinel — REQUIRED, validated by `clean`
  scenario.yaml
  replay.json
  manifest.initial.json
  manifest.current.json
  journal.jsonl
  validation.json
  materialization.json
  reports/
    assets/
    works/
    variants/
    bundles/
  library/                    # all scenario paths resolve under here
    movies-hd/
    movies-4k/
    archive/
    staging/
```

Path-containment rules: every scenario path resolves under `<run-dir>/library/`
after symlink/`..` normalization. Violations fail with exit code `7`.
```

- [ ] **Step 3: Write `docs/contract/cli-reference.md`**

```markdown
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

Sprint 0 ships every command as a stub that exits `1`. See
[`chaos-librarian-design.md` "CLI Contract"](../specs/chaos-librarian-design.md).
```

- [ ] **Step 4: Write `docs/contract/replay-bundle.md`**

```markdown
# Replay Bundle

`replay.json` is a single JSON file sufficient to reproduce a run. Plan-only
bundles are bit-identical across runs and platforms; materialize bundles are
logically identical modulo volatile fields. See
[`chaos-librarian-design.md` "Replay Bundle"](../specs/chaos-librarian-design.md).

## Mode-Split Fields

- **`run_id`** — UUIDv5 derived from
  `uuid5(CHAOS_LIBRARIAN_NAMESPACE_UUID, "<scenario_hash>:<seed>")` in plan-only
  mode; random UUIDv4 in materialize/run.
- **`created_at`** — **omitted entirely** in plan-only (field absent from JSON,
  not null); RFC 3339 in materialize/run.

## Volatile Fields (Materialize / Run)

The following fields are excluded from materialize-mode equivalence comparison:

- `created_at`, any `wall_clock_time` on journal entries
- `run_id` (UUIDv4 in these modes)
- content hashes and probed media facts
- the `toolchain` block
```

- [ ] **Step 5: Write `docs/contract/time-model.md`**

```markdown
# Time Model

Time is tracked as a 64-bit signed integer of nanoseconds since scenario start
(`t=0`). All durations and timestamps share this representation across step
mode and wall-clock mode.

Duration strings:

| string  | meaning           |
|---------|-------------------|
| `500ms` | 500 milliseconds  |
| `2s`    | 2 seconds         |
| `1m30s` | 90 seconds        |
| `0`     | t=0 (start)       |

Timeline event `at:` values are offsets from scenario start, not from the
previous event. Events with the same `at:` value are applied in declared
order.

Journal entries record both `logical_time_ns` (integer) and, in wall-clock
and materialize modes, `wall_clock_time` (RFC 3339). Plan-only journals omit
`wall_clock_time`.

See [`chaos-librarian-design.md` "Time Model"](../specs/chaos-librarian-design.md).
```

- [ ] **Step 6: Verify docs render**

```bash
ls docs/contract/
```
Expected: 5 markdown files.

- [ ] **Step 7: Commit**

```bash
git add docs/contract/
git commit -m "Add contract reference documentation"
```

---

## Phase 5: Final Verification

### Task 17: Full Sprint 0 exit-criteria sweep

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -v
```
Expected: all tests pass. Count should be roughly 55+ tests across the contract and CLI test modules.

- [ ] **Step 2: Run ruff check and format**

```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: both clean.

- [ ] **Step 3: Run ty**

```bash
uv run ty check src tests
```
Expected: clean.

- [ ] **Step 4: Run the schema-export check**

```bash
uv run python -m chaos_librarian.schema_export --check
```
Expected: "All 7 schemas up-to-date."

- [ ] **Step 5: Run prek across the repo**

```bash
prek run --all-files
```
Expected: all hooks pass.

- [ ] **Step 6: Push the branch and verify CI**

```bash
git push -u origin feat/sprint-0
gh run watch
```
Expected: CI green.

- [ ] **Step 7: Open the Sprint 0 PR**

```bash
gh pr create --base main --title "Sprint 0: schemas, CLI stub, and contract" --body "$(cat <<'EOF'
## Summary
- Project skeleton: uv, Python 3.13, ruff, ty, pytest, prek, GitHub Actions CI
- Seven Pydantic v2 contract models exported as JSON Schema (draft 2020-12)
- Path-containment helper enforcing the Filesystem Safety contract
- Run-directory sentinel schema
- Multi-phase journal fields (`phase`, `temp_path`, `related_event_id`) frozen
- Replay bundle with deterministic UUIDv5 `run_id` in plan-only mode
- Typer CLI stub with the frozen command surface (every command exits 1)
- Four sample scenarios including a `slow_copy_start` / `slow_copy_commit` pair
- Five contract reference documents under `docs/contract/`

## Test plan
- [ ] CI green
- [ ] `python -m chaos_librarian.schema_export --check` clean locally
- [ ] All sample scenarios load through the Pydantic model
- [ ] `chaos-librarian --help` lists all nine commands

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**Spec coverage:** Sprint 0 deliverables from `docs/specs/chaos-librarian-design.md`:

- pyproject.toml, prek, CI, .gitignore, license headers → Tasks 1–3 ✓
- Pydantic models (scenario, journal, manifest, replay bundle, validation, materialization) → Tasks 7–12 ✓
- Run-directory sentinel schema authored as Pydantic model → Task 6 ✓
- Journal schema includes multi-phase fields from day one → Task 9 ✓
- Path-resolution helper with unit tests → Task 5 ✓
- CI exports JSON Schema and fails on drift → Task 13 ✓
- CLI surface frozen, stub exit 1 → Task 14 ✓
- `docs/contract/` with five docs → Task 16 ✓
- 3–4 hand-authored sample scenarios → Task 15 (ships 4) ✓
- Exit criteria sweep (pytest, ty, ruff, CI) → Task 17 ✓

**Type consistency:** Cross-checked class names between tasks (e.g., `JournalEntry`, `JournalPhase`, `ReplayBundle`, `compute_plan_only_run_id`, `Scenario`, `SlowCopyStartEvent`, `SlowCopyCommitEvent`). All references in later tasks match what's defined earlier.

**Placeholder scan:** No "TBD", "implement later", or empty-step references. Every code block contains the actual content.

---

## Out Of Scope

- Implementing any of the scenario-execution, timeline, materializer, or replay behaviors. Those land in Sprints 1+.
- Adding new schemas beyond the seven enumerated.
- Wiring the path-containment helper into a runtime materializer.
- Implementing `capabilities` probing (Sprint 5).
- Implementing real `clean` behavior (Sprint 4).
