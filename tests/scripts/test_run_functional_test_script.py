"""Contract checks for the functional-test runner."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run-functional-test.sh"


def test_functional_script_is_executable_shell() -> None:
    """The checked-in runner should be executable and parse as Bash."""
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)

    result = subprocess.run(["bash", "-n", str(SCRIPT)], check=False)

    assert result.returncode == 0


def test_functional_script_help_documents_coverage_and_scan_evidence() -> None:
    """Help output should tell operators what evidence the run captures."""
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    output = result.stdout.lower()
    for expected in (
        "capabilities",
        "plan",
        "step",
        "replay",
        "materialize",
        "run",
        "tree scan",
        "mtime",
        "size",
        "sha256",
        "active-library-churn",
        "version-evolution",
        "subtitle-ops-on-mp4",
        "malformed-container-header",
        "interceptor-catalog-run",
    ):
        assert expected in output


def test_functional_script_requires_media_mutation_readiness(tmp_path: Path) -> None:
    """The reviewed run should fail instead of silently skipping media coverage."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            from __future__ import annotations

            import json
            import subprocess
            import sys

            args = sys.argv[1:]
            if args[:2] == ["run", "python"]:
                completed = subprocess.run([sys.executable, *args[2:]], check=False)
                raise SystemExit(completed.returncode)

            if args[:3] == ["run", "chaos-librarian", "capabilities"]:
                print(
                    json.dumps(
                        {{
                            "ready_for": {{
                                "materialize_static": True,
                                "materialize_filesystem_mutations": True,
                                "materialize_media_mutations": False,
                            }}
                        }}
                    )
                )
                raise SystemExit(0)

            print(f"unexpected command after capability gate: {{args}}", file=sys.stderr)
            raise SystemExit(99)
            """
        ),
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(SCRIPT)],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=4,
    )

    assert result.returncode == 4
    assert "ready_for.materialize_media_mutations: false" in result.stdout
    assert "media mutation readiness is required" in result.stdout
    assert "unexpected command after capability gate" not in result.stdout


def test_wall_clock_failure_prints_child_output_without_library_timeout(
    tmp_path: Path,
) -> None:
    """A failed wall-clock child should surface its captured output promptly."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            from __future__ import annotations

            import json
            import subprocess
            import sys
            from pathlib import Path


            def option_value(args: list[str], name: str) -> str:
                return args[args.index(name) + 1]


            def write_plan_artifacts(out_dir: Path) -> None:
                out_dir.mkdir(parents=True, exist_ok=True)
                manifest = {{
                    "assets": [{{"id": "asset-a", "bundle_id": "bundle-a"}}],
                    "bundles": [{{"id": "bundle-a", "variant_id": "variant-a"}}],
                    "locations": [{{"asset_id": "asset-a", "path": "movies/Synthetic - hd.mkv"}}],
                    "movies": [{{"id": "movie-a", "title": "Synthetic", "layout": "movie_flat"}}],
                    "series": [],
                    "seasons": [],
                    "episodes": [],
                    "artists": [],
                    "albums": [],
                    "discs": [],
                    "tracks": [],
                    "sidecars": [],
                    "variants": [
                        {{
                            "id": "variant-a",
                            "parent_kind": "movie",
                            "parent_id": "movie-a",
                            "label": "hd",
                        }}
                    ],
                    "versions": [
                        {{
                            "asset_id": "asset-a",
                            "content_hash": "sha256:" + "0" * 64,
                            "probed": None,
                        }}
                    ],
                }}
                replay = {{"run_id": "00000000-0000-0000-0000-000000000000"}}
                (out_dir / "manifest.current.json").write_text(
                    json.dumps(manifest),
                    encoding="utf-8",
                )
                (out_dir / "replay.json").write_text(
                    json.dumps(replay),
                    encoding="utf-8",
                )


            args = sys.argv[1:]
            if args[:2] == ["run", "python"]:
                completed = subprocess.run([sys.executable, *args[2:]], check=False)
                raise SystemExit(completed.returncode)

            if args[:2] != ["run", "chaos-librarian"]:
                print(f"unexpected uv arguments: {{args}}", file=sys.stderr)
                raise SystemExit(99)

            command = args[2]
            if command == "capabilities":
                print(
                    json.dumps(
                        {{
                            "ready_for": {{
                                "materialize_static": True,
                                "materialize_filesystem_mutations": True,
                                "materialize_media_mutations": True,
                            }}
                        }}
                    )
                )
            elif command == "compare":
                observed = json.loads(Path(args[4]).read_text(encoding="utf-8"))
                if observed.get("schema_version") != 2:
                    print("observed schema_version is not v2", file=sys.stderr)
                    raise SystemExit(42)
                if "works" in observed:
                    print("observed still contains works", file=sys.stderr)
                    raise SystemExit(42)
                asset = observed["assets"][0]
                if "work_ref" in asset:
                    print("observed asset still contains work_ref", file=sys.stderr)
                    raise SystemExit(42)
                variant = observed["variants"][0]
                if "work_ref" in variant:
                    print("observed variant still contains work_ref", file=sys.stderr)
                    raise SystemExit(42)
                if variant["parent_kind"] != "movie" or variant["parent_ref"] != "movie-a":
                    print("observed variant parent ref is wrong", file=sys.stderr)
                    raise SystemExit(42)
                if observed["movies"][0]["observed_ref"] != "movie-a":
                    print("observed movie row missing", file=sys.stderr)
                    raise SystemExit(42)
                print(json.dumps({{"ok": True, "command": command}}))
            elif command in {{"validate", "step", "inspect"}}:
                print(json.dumps({{"ok": True, "command": command}}))
            elif command == "plan":
                write_plan_artifacts(Path(option_value(args, "--out")))
                print(json.dumps({{"ok": True, "command": command}}))
            elif command == "replay":
                out_dir = Path(option_value(args, "--out"))
                out_dir.mkdir(parents=True, exist_ok=True)
                print(json.dumps({{"ok": True, "command": command}}))
            elif command == "materialize":
                out_dir = Path(option_value(args, "--out"))
                (out_dir / "library").mkdir(parents=True, exist_ok=True)
                (out_dir / "library" / "asset.txt").write_text("asset", encoding="utf-8")
                print(json.dumps({{"ok": True, "command": command}}))
            elif command == "run":
                print("simulated run failure before library publish", file=sys.stderr)
                raise SystemExit(5)
            else:
                print(f"unhandled chaos-librarian command: {{command}}", file=sys.stderr)
                raise SystemExit(99)
            """
        ),
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    try:
        result = subprocess.run(
            [str(SCRIPT)],
            check=False,
            capture_output=True,
            env=env,
            text=True,
            timeout=4,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("runner waited for library timeout instead of surfacing child failure")

    assert result.returncode == 5
    assert "wall-clock command output: slow-copy-materialize" in result.stdout
    assert "simulated run failure before library publish" in result.stdout
    assert "timed out waiting" not in result.stdout
