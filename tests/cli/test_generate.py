"""CLI tests for deterministic scenario generation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from click.testing import Result
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.cli.commands import generate as generate_cmd
from chaos_librarian.contract.profiles import CANONICAL_FUZZ_LANES, FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import api as generation_api
from chaos_librarian.scenario_io import parse_scenario_bytes

runner = CliRunner()
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain_output(result: Result) -> str:
    return _ANSI_ESCAPE_RE.sub("", result.stdout + result.stderr)


def _load_generated(path: Path) -> Scenario:
    raw, _ = parse_scenario_bytes(path.read_bytes(), source=path)
    return Scenario.model_validate(raw)


def test_generate_writes_valid_yaml_and_json_summary(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--seed",
            "123",
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["profile"] == "fuzz-smoke"
    assert payload["lane"] == FuzzLaneName.SMOKE.value
    assert payload["seed"] == 123
    assert payload["scenario_id"] == "fuzz-smoke-smoke-seed-123"
    assert payload["scenario_path"] == str(out.resolve())
    assert len(payload["sha256"]) == 64
    assert _load_generated(out).scenario_id == "fuzz-smoke-smoke-seed-123"


def test_generate_json_validates_generated_yaml_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "generated.yaml"
    calls = 0
    original_run_validation = generation_api.run_validation

    def counting_run_validation(run_input: Any) -> Any:
        nonlocal calls
        calls += 1
        return original_run_validation(run_input)

    monkeypatch.setattr(generation_api, "run_validation", counting_run_validation)

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--seed",
            "123",
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == 1


def test_generate_regression_requires_lane(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-regression", "--seed", "456", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert "--lane is required for fuzz-regression" in _plain_output(result)
    assert not out.exists()


def test_generate_rejects_lane_profile_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--lane",
            "media-rewrite",
            "--seed",
            "123",
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 2
    assert "lane media-rewrite is not valid for fuzz-smoke" in _plain_output(result)
    assert not out.exists()


def test_generate_accepts_topology_lanes(tmp_path: Path) -> None:
    for lane in ("tv-topology", "music-topology"):
        out = tmp_path / f"{lane}.yaml"
        result = runner.invoke(
            app,
            [
                "generate",
                "--profile",
                "fuzz-regression",
                "--lane",
                lane,
                "--seed",
                "463",
                "--out",
                str(out),
            ],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert _load_generated(out).generation is not None


def test_generate_rejects_existing_out(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"
    out.write_text("existing", encoding="utf-8")

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-smoke", "--seed", "123", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert out.read_text(encoding="utf-8") == "existing"


def test_generate_rejects_random_seed(tmp_path: Path) -> None:
    out = tmp_path / "generated.yaml"

    result = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-smoke", "--seed", "random", "--out", str(out)],
    )

    assert result.exit_code == 2
    assert not out.exists()


def _run(args: list[str]) -> Result:
    return runner.invoke(app, args)


def test_batch_smoke_writes_count_files(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 0, _plain_output(result)
    files = sorted(p.name for p in out.glob("*.yaml"))
    assert files == [
        "fuzz-smoke-smoke-seed-42.yaml",
        "fuzz-smoke-smoke-seed-43.yaml",
        "fuzz-smoke-smoke-seed-44.yaml",
    ]
    for path in out.glob("*.yaml"):
        assert _load_generated(path).generation is not None


def test_batch_regression_cycles_lanes(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    order = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION]

    result = _run(
        [
            "generate",
            "--profile",
            "fuzz-regression",
            "--count",
            str(len(order)),
            "--seed",
            "100",
            "--out",
            str(out),
        ]
    )

    assert result.exit_code == 0, _plain_output(result)
    # ``ty`` rejects ``.generation.lane`` on the optional ``ScenarioGeneration |
    # None`` and ignore-comments do not suppress it; narrow with an assert,
    # matching this file's existing convention.
    lanes: set[str] = set()
    for path in out.glob("*.yaml"):
        gen = _load_generated(path).generation
        assert gen is not None
        lanes.add(gen.lane.value)
    assert lanes == {lane.value for lane in order}
    assert len(list(out.glob("*.yaml"))) == len(order)


def test_batch_explicit_lane_uses_one_lane(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    result = _run(
        [
            "generate",
            "--profile",
            "fuzz-regression",
            "--lane",
            "core-fs",
            "--count",
            "4",
            "--seed",
            "10",
            "--out",
            str(out),
        ]
    )

    assert result.exit_code == 0, _plain_output(result)
    files = sorted(p.name for p in out.glob("*.yaml"))
    assert files == [f"fuzz-regression-core-fs-seed-{s}.yaml" for s in (10, 11, 12, 13)]


def test_batch_is_deterministic(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    out_a.mkdir()
    out_b.mkdir()
    args = ["generate", "--profile", "fuzz-regression", "--count", "5", "--seed", "7", "--out"]

    assert _run([*args, str(out_a)]).exit_code == 0
    assert _run([*args, str(out_b)]).exit_code == 0

    names_a = sorted(p.name for p in out_a.glob("*.yaml"))
    names_b = sorted(p.name for p in out_b.glob("*.yaml"))
    assert names_a == names_b
    for name in names_a:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()


def test_batch_json_emits_only_summary_object(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    result = _run(
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--count",
            "3",
            "--seed",
            "42",
            "--out",
            str(out),
            "--json",
        ]
    )

    assert result.exit_code == 0, _plain_output(result)
    payload = json.loads(result.stdout)  # must parse — no progress lines on stdout
    assert payload["ok"] is True
    assert payload["count"] == 3
    assert payload["out_dir"] == str(out.resolve())
    assert [s["seed"] for s in payload["scenarios"]] == [42, 43, 44]


def test_batch_matches_single_file_output(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    single = tmp_path / "single.yaml"

    assert (
        _run(
            [
                "generate",
                "--profile",
                "fuzz-regression",
                "--count",
                "3",
                "--seed",
                "200",
                "--out",
                str(batch_dir),
            ]
        ).exit_code
        == 0
    )
    # item index 1 of the cycle: second canonical lane, seed 201
    lane = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION][1].value
    assert (
        _run(
            [
                "generate",
                "--profile",
                "fuzz-regression",
                "--lane",
                lane,
                "--seed",
                "201",
                "--out",
                str(single),
            ]
        ).exit_code
        == 0
    )

    batch_file = batch_dir / f"fuzz-regression-{lane}-seed-201.yaml"
    assert batch_file.read_bytes() == single.read_bytes()


def test_batch_rejects_missing_out_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    result = _run(
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--count",
            "2",
            "--seed",
            "1",
            "--out",
            str(missing),
        ],
    )

    assert result.exit_code == 2
    assert not missing.exists()


def test_batch_rejects_out_that_is_a_file(tmp_path: Path) -> None:
    out = tmp_path / "afile"
    out.write_text("x", encoding="utf-8")

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "2", "--seed", "1", "--out", str(out)]
    )

    assert result.exit_code == 2
    assert out.read_text(encoding="utf-8") == "x"


def test_batch_collision_pre_check_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    # pre-create a file that the batch would target
    (out / "fuzz-smoke-smoke-seed-43.yaml").write_text("pre", encoding="utf-8")

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 2
    # no new files written; the pre-existing file is untouched
    assert sorted(p.name for p in out.glob("*.yaml")) == ["fuzz-smoke-smoke-seed-43.yaml"]
    assert (out / "fuzz-smoke-smoke-seed-43.yaml").read_text(encoding="utf-8") == "pre"


def test_batch_rollback_removes_written_files_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    real_generate = generate_cmd.generate_scenario
    calls = {"n": 0}

    def failing_generate(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real_generate(**kwargs)

    monkeypatch.setattr(generate_cmd, "generate_scenario", failing_generate)

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 1
    assert "rolled back" in _plain_output(result)
    # first file was written then rolled back; nothing remains
    assert list(out.glob("*.yaml")) == []


def test_batch_rollback_warns_when_a_file_cannot_be_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    target = "fuzz-smoke-smoke-seed-42.yaml"

    real_generate = generate_cmd.generate_scenario
    calls = {"n": 0}

    def failing_generate(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real_generate(**kwargs)

    real_unlink = Path.unlink

    def selective_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self.name == target:
            raise OSError("locked")
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(generate_cmd, "generate_scenario", failing_generate)
    monkeypatch.setattr(Path, "unlink", selective_unlink)

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 1
    assert "could not remove" in _plain_output(result)
    # the un-removable file is still on disk and surfaced, not silently dropped
    assert (out / target).exists()
    assert target in _plain_output(result)
