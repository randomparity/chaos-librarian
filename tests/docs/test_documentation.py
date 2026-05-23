from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
DOCS = ROOT / "docs"


USER_DOCS = [
    "user/installation.md",
    "user/quickstart.md",
    "user/scenario-authoring.md",
    "user/commands.md",
    "user/run-artifacts.md",
    "user/integration.md",
    "user/troubleshooting.md",
]

DEVELOPER_DOCS = [
    "developer/architecture.md",
    "developer/contracts-and-schemas.md",
    "developer/validation-pipeline.md",
    "developer/timeline-engine.md",
    "developer/materializer.md",
    "developer/adapter-compare.md",
    "developer/testing.md",
    "developer/release-checklist.md",
]

CONTRACT_DOCS = [
    "contract/cli-reference.md",
    "contract/schema-reference.md",
    "contract/fixture-layout.md",
    "contract/replay-bundle.md",
    "contract/time-model.md",
    "contract/manifest-initial-state.md",
    "contract/observed-state.md",
    "contract/divergence-report.md",
    "contract/integration-recipes.md",
]

CLI_COMMANDS = [
    "validate",
    "plan",
    "materialize",
    "run",
    "step",
    "replay",
    "inspect",
    "capabilities",
    "clean",
    "compare",
]

TIMELINE_ACTIONS = [
    "move_asset",
    "rename_file",
    "delete_file",
    "add_file",
    "reencode_video",
    "reencode_audio",
    "create_sidecar",
    "slow_copy_start",
    "slow_copy_commit",
    "archive_file",
    "move_between_roots",
    "remux_container",
    "edit_metadata",
    "embed_subtitle",
    "extract_subtitle",
    "remove_sidecar",
    "update_sidecar",
    "corrupt_container_header",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_contains_mvp_quickstart_and_feature_map() -> None:
    text = _read(README)

    required_snippets = [
        "Scenario-driven synthetic media library simulator",
        "## Features",
        "## Quick Start",
        "uv sync",
        "uv run chaos-librarian capabilities --json",
        "uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json",
        "uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml",
        'uv run chaos-librarian inspect "$RUN_DIR" --json',
        "## Documentation",
        "docs/README.md",
    ]
    for snippet in required_snippets:
        assert snippet in text


def test_docs_index_links_to_user_developer_and_contract_guides() -> None:
    docs_index = DOCS / "README.md"
    expected_paths = [*USER_DOCS, *DEVELOPER_DOCS, *CONTRACT_DOCS]
    missing = [
        relative_path for relative_path in expected_paths if not (DOCS / relative_path).is_file()
    ]

    assert docs_index.is_file(), "docs/README.md is missing"
    assert not missing, f"missing documentation files: {missing}"

    text = _read(DOCS / "README.md")

    for relative_path in expected_paths:
        assert f"]({relative_path})" in text, relative_path


def test_contract_cli_reference_matches_current_cli_surface() -> None:
    text = _read(DOCS / "contract" / "cli-reference.md")

    for command in CLI_COMMANDS:
        assert f"chaos-librarian {command}" in text
    assert "`run` remains a stub" not in text
    assert "stub" not in text.lower()
    assert "--duration" in text
    assert "--speed" in text


def test_contract_docs_do_not_preserve_known_stale_guidance() -> None:
    fixture_layout = _read(DOCS / "contract" / "fixture-layout.md")
    initial_state = _read(DOCS / "contract" / "manifest-initial-state.md")
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")
    schema_reference = _read(DOCS / "contract" / "schema-reference.md")

    assert "`reports/` are written by plan, materialize, and run outputs." in fixture_layout
    assert "written by later" not in fixture_layout
    assert "add_file` timeline event at `t=0`" not in initial_state
    assert "`move_asset` timeline event at `t=0`" in initial_state
    assert "chaos-librarian materialize scenario.yaml --out run-dir" in integration_recipes
    assert "chaos-librarian plan scenario.yaml --out run-dir" not in integration_recipes
    assert "readers MUST reject unknown versions with exit code `3`" not in schema_reference


def test_user_docs_describe_current_replay_support() -> None:
    commands = _read(DOCS / "user" / "commands.md")
    run_artifacts = _read(DOCS / "user" / "run-artifacts.md")

    assert "Replay a recorded plan-only or wall-clock run bundle" in commands
    assert "Materialize-mode replay is not implemented" in commands
    assert "plan-only and wall-clock run bundles" in run_artifacts
    assert "materialize-mode replay is not implemented" in run_artifacts


def test_user_docs_cover_commands_and_timeline_actions() -> None:
    commands_path = DOCS / "user" / "commands.md"
    scenario_path = DOCS / "user" / "scenario-authoring.md"

    assert commands_path.is_file(), "docs/user/commands.md is missing"
    assert scenario_path.is_file(), "docs/user/scenario-authoring.md is missing"

    commands = _read(commands_path)
    scenario = _read(scenario_path)

    for command in CLI_COMMANDS:
        assert command in commands
    for action in TIMELINE_ACTIONS:
        assert action in scenario
