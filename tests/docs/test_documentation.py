from __future__ import annotations

from pathlib import Path

from chaos_librarian.cli.app import app
from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    CAPABILITIES_SCHEMA_VERSION,
    DIVERGENCE_SCHEMA_VERSION,
    JOURNAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    OBSERVED_STATE_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
    WORK_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.scenario import TimelineActionName

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

SCHEMA_VERSIONS = {
    "scenario": SCENARIO_SCHEMA_VERSION,
    "manifest": MANIFEST_SCHEMA_VERSION,
    "journal": JOURNAL_SCHEMA_VERSION,
    "replay bundle": REPLAY_BUNDLE_SCHEMA_VERSION,
    "validation": VALIDATION_SCHEMA_VERSION,
    "materialization": MATERIALIZATION_SCHEMA_VERSION,
    "run sentinel": RUN_SENTINEL_SCHEMA_VERSION,
    "asset report": ASSET_REPORT_SCHEMA_VERSION,
    "work report": WORK_REPORT_SCHEMA_VERSION,
    "variant report": VARIANT_REPORT_SCHEMA_VERSION,
    "bundle report": BUNDLE_REPORT_SCHEMA_VERSION,
    "capabilities": CAPABILITIES_SCHEMA_VERSION,
    "observed state": OBSERVED_STATE_SCHEMA_VERSION,
    "divergence": DIVERGENCE_SCHEMA_VERSION,
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _markdown_section(text: str, heading: str) -> str:
    start = text.index(f"## {heading}")
    next_section = text.find("\n## ", start + 1)
    if next_section == -1:
        return text[start:]
    return text[start:next_section]


def _cli_command_names() -> list[str]:
    names: list[str] = []
    for command in app.registered_commands:
        if command.callback is None:
            continue
        callback_name = getattr(command.callback, "__name__", None)
        assert isinstance(callback_name, str)
        name = command.name or callback_name.replace("_", "-")
        names.append(name)
    return names


def test_readme_contains_mvp_quickstart_and_feature_map() -> None:
    text = _read(README)
    quick_start = _markdown_section(text, "Quick Start")

    required_snippets = [
        "Scenario-driven synthetic media library simulator",
        "## Features",
        "## Quick Start",
        "uv sync",
        "uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json",
        "uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml",
        'uv run chaos-librarian inspect "$RUN_DIR" --json',
        "## Documentation",
        "docs/README.md",
    ]
    for snippet in required_snippets:
        assert snippet in text
    assert "uv run chaos-librarian capabilities --json" not in quick_start


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

    for command in _cli_command_names():
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


def test_performance_profile_policy_docs_are_discoverable() -> None:
    source_design = _read(DOCS / "specs" / "chaos-librarian-design.md")
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")
    testing = _read(DOCS / "developer" / "testing.md")

    assert "## Performance Profile Policy" in source_design
    assert "Minimum free disk before run" in source_design
    assert (
        "Larger performance profiles that satisfy the Performance Profile Policy" in source_design
    )
    assert "performance-smoke" in integration_recipes
    assert "performance-scale" in integration_recipes
    assert "performance-stress" in integration_recipes
    assert "No performance profiles by default" in integration_recipes
    assert "Performance Profile Policy" in testing


def test_network_filesystem_lag_profile_policy_docs_are_discoverable() -> None:
    source_design = _read(DOCS / "specs" / "chaos-librarian-design.md")
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")
    time_model = _read(DOCS / "contract" / "time-model.md")
    testing = _read(DOCS / "developer" / "testing.md")

    assert "## Network Filesystem Lag Profile Policy" in source_design
    assert "`network-fs-lag`" in source_design
    assert (
        "Network filesystem lag profile that satisfies "
        "the Network Filesystem Lag Profile Policy" in source_design
    )
    assert "Network Filesystem Lag" in integration_recipes
    assert "path-state windows" in integration_recipes
    assert "Network lag profiles use the existing duration grammar" in time_model
    assert "same logical clock as timeline events" in time_model
    assert "Network Filesystem Lag Profile Testing" in testing


def test_fuzz_profile_generation_docs_are_discoverable() -> None:
    source_design = _read(DOCS / "specs" / "chaos-librarian-design.md")
    cli_reference = _read(DOCS / "contract" / "cli-reference.md")
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")
    testing = _read(DOCS / "developer" / "testing.md")

    assert "## Fuzz Profile Generation Policy" in source_design
    assert "`fuzz-smoke`" in source_design
    assert "`fuzz-regression`" in source_design
    assert "chaos-librarian generate --profile fuzz-smoke" in cli_reference
    assert "Fuzz Profile Generation" in integration_recipes
    assert "Replay never calls the generator" in integration_recipes
    assert "Fuzz Profile Generation Testing" in testing


def test_duplicate_variant_expansion_pack_docs_are_discoverable() -> None:
    source_design = _read(DOCS / "specs" / "chaos-librarian-design.md")
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")

    assert "duplicate-variant-expanded.yaml" in source_design
    assert "Duplicate And Variant Pack" in integration_recipes
    assert "pathless topology export can surface the ambiguous" in integration_recipes


def test_schema_reference_lists_current_contract_versions() -> None:
    text = _read(DOCS / "contract" / "schema-reference.md")

    for artifact, version in SCHEMA_VERSIONS.items():
        assert f"| {artifact} | {version} |" in text


def test_developer_docs_match_current_loader_and_capability_behavior() -> None:
    adapter_compare = _read(DOCS / "developer" / "adapter-compare.md")
    materializer = _read(DOCS / "developer" / "materializer.md")
    testing = _read(DOCS / "developer" / "testing.md")

    assert "If `reports/` is present" in adapter_compare
    assert "if `reports/` is absent, the loader derives reports" in adapter_compare
    assert "CLI startup gate for `materialize` and `run`" in materializer
    assert "not as an extra" in materializer
    assert "startup gate" in materializer
    assert "uv run pytest tests/cli/test_plan.py -q --no-cov" in testing
    assert "uv run pytest tests/validation/rules/test_timeline_lifecycle.py -q --no-cov" in testing
    assert "Use `--no-cov`" in testing
    assert "for subset checks" in testing
    assert "full\n`uv run pytest` suite" in testing


def test_user_docs_describe_current_replay_support() -> None:
    commands = _read(DOCS / "user" / "commands.md")
    run_artifacts = _read(DOCS / "user" / "run-artifacts.md")
    troubleshooting = _read(DOCS / "user" / "troubleshooting.md")

    assert "Replay a recorded plan-only or wall-clock run bundle" in commands
    assert "Materialize-mode replay is not implemented" in commands
    assert "plan-only and wall-clock run bundles" in run_artifacts
    assert "materialize-mode replay is not implemented" in run_artifacts
    assert "Install or upgrade ffmpeg or ffprobe" in troubleshooting
    assert "ready_for.materialize_media_mutations" in troubleshooting


def test_user_docs_cover_commands_and_timeline_actions() -> None:
    commands_path = DOCS / "user" / "commands.md"
    scenario_path = DOCS / "user" / "scenario-authoring.md"

    assert commands_path.is_file(), "docs/user/commands.md is missing"
    assert scenario_path.is_file(), "docs/user/scenario-authoring.md is missing"

    commands = _read(commands_path)
    scenario = _read(scenario_path)

    for command in _cli_command_names():
        assert command in commands
    for action in TimelineActionName:
        assert action.value in scenario
