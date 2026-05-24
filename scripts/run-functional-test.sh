#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/run-functional-test.sh

Run a local functional test of Chaos Librarian and write a reviewed log under
chaos-test-out/functional-<timestamp>-<pid>/functional-test.log.

The run exercises these CLI commands:
  capabilities, validate, plan, step, replay, inspect, compare, materialize,
  run, clean

The run covers these scenario fixtures:
  active-library-churn       plan/step/replay plus filesystem, sidecar, and
                             metadata mutation coverage
  duplicate-variant-expanded static multi-work/multi-variant materialization
  version-evolution          reencode_video, reencode_audio, edit_metadata
  subtitle-ops-on-mp4        remux_container and embed_subtitle
  embed-extract-roundtrip    embed_subtitle and extract_subtitle
  malformed-container-header corrupt_container_header
  negative-oracle-hash       wrong_oracle_hash
  interceptor-catalog        truncate_file and touch_mtime
  slow-copy-materialize      wall-clock slow-copy creation scans
  interceptor-catalog-run    wall-clock network-lag mutation scans

Tree scan evidence records path, mtime, size, and sha256 for files at relevant
intervals so the log shows files being created, modified, renamed, and removed.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 0 ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
RUN_ROOT="$REPO_ROOT/chaos-test-out/functional-${STAMP}-$$"
LOG_PATH="$RUN_ROOT/functional-test.log"
ACTIVE_CHILD=""

mkdir -p "$RUN_ROOT"
cd "$REPO_ROOT"

exec > >(tee "$LOG_PATH") 2>&1

cleanup_child() {
  if [[ -z "$ACTIVE_CHILD" ]]; then
    return
  fi
  if kill -0 "$ACTIVE_CHILD" 2>/dev/null; then
    kill "$ACTIVE_CHILD" 2>/dev/null || true
    wait "$ACTIVE_CHILD" 2>/dev/null || true
  fi
  ACTIVE_CHILD=""
}

trap cleanup_child EXIT INT TERM

run_python() {
  uv run python "$@"
}

section() {
  printf '\n=== %s ===\n' "$1"
}

run_cmd() {
  printf '$'
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

child_is_running() {
  local running_pid

  if [[ -z "$ACTIVE_CHILD" ]]; then
    return 1
  fi
  while IFS= read -r running_pid; do
    if [[ "$running_pid" == "$ACTIVE_CHILD" ]]; then
      return 0
    fi
  done < <(jobs -r -p)
  return 1
}

print_wall_clock_command_output() {
  local scenario="$1"
  local command_log="$2"

  section "wall-clock command output: $scenario"
  if [[ -f "$command_log" ]]; then
    cat "$command_log"
  else
    printf '(missing command log: %s)\n' "$command_log"
  fi
}

finish_wall_clock_command() {
  local scenario="$1"
  local command_log="$2"
  local status

  set +e
  wait "$ACTIVE_CHILD"
  status="$?"
  ACTIVE_CHILD=""
  set -e

  print_wall_clock_command_output "$scenario" "$command_log"
  if [[ "$status" -ne 0 ]]; then
    printf 'wall-clock run failed for %s with exit code %s\n' "$scenario" "$status" >&2
    exit "$status"
  fi
}

fail_wall_clock_timeout() {
  local scenario="$1"
  local command_log="$2"
  local out_dir="$3"

  printf 'timed out waiting for %s/library\n' "$out_dir" >&2
  cleanup_child
  print_wall_clock_command_output "$scenario" "$command_log"
  exit 124
}

scenario_path() {
  printf '%s/tests/fixtures/scenarios/%s.yaml' "$REPO_ROOT" "$1"
}

scan_tree() {
  local label="$1"
  local root="$2"

  section "tree scan: $label"
  printf 'root: %s\n' "$root"
  printf 'columns: path | mtime_utc | size_bytes | sha256\n'
  run_python - "$root" <<'PY'
from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
if not root.exists():
    print("(missing)")
    raise SystemExit(0)
if not root.is_dir():
    print("(not a directory)")
    raise SystemExit(0)

files = sorted(path for path in root.rglob("*") if path.is_file())
if not files:
    print("(no files)")
    raise SystemExit(0)

for path in files:
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    mtime = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(timespec="microseconds")
    rel_path = path.relative_to(root).as_posix()
    print(f"{rel_path} | {mtime} | {stat.st_size} | sha256:{digest}")
PY
}

parse_capabilities() {
  local capabilities_path="$1"
  run_python - "$capabilities_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
ready_for = payload["ready_for"]
print(
    str(ready_for["materialize_static"]).lower(),
    str(ready_for["materialize_filesystem_mutations"]).lower(),
    str(ready_for["materialize_media_mutations"]).lower(),
)
PY
}

write_observed_from_fixture() {
  local run_dir="$1"
  local observed_path="$2"

  run_python - "$run_dir" "$observed_path" <<'PY'
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

run_dir = Path(sys.argv[1])
observed_path = Path(sys.argv[2])
manifest = json.loads((run_dir / "manifest.current.json").read_text(encoding="utf-8"))
replay = json.loads((run_dir / "replay.json").read_text(encoding="utf-8"))

versions_by_asset = {version["asset_id"]: version for version in manifest["versions"]}
locations_by_asset = {location["asset_id"]: location for location in manifest["locations"]}
sidecars_by_asset = defaultdict(list)
for sidecar in manifest["sidecars"]:
    sidecars_by_asset[sidecar["asset_id"]].append(
        {
            "observed_ref": f"observed-{sidecar['id']}",
            "kind": sidecar["kind"],
            "path": sidecar["path"],
            "content_hash": sidecar.get("content_hash"),
        }
    )

bundles = {bundle["id"]: bundle for bundle in manifest["bundles"]}
variants = {variant["id"]: variant for variant in manifest["variants"]}
bundle_asset_refs = defaultdict(list)
for asset in manifest["assets"]:
    bundle_asset_refs[asset["bundle_id"]].append(asset["id"])

assets = []
for asset in manifest["assets"]:
    version = versions_by_asset.get(asset["id"], {})
    location = locations_by_asset.get(asset["id"])
    bundle = bundles[asset["bundle_id"]]
    variant = variants[bundle["variant_id"]]
    assets.append(
        {
            "observed_ref": asset["id"],
            "current_path": location["path"] if location else None,
            "content_hash": version.get("content_hash"),
            "probed": version.get("probed"),
            "work_ref": variant["work_id"],
            "variant_ref": variant["id"],
            "bundle_ref": bundle["id"],
            "sidecars": sidecars_by_asset[asset["id"]],
        }
    )

observed = {
    "schema_version": 1,
    "consumer": {"name": "functional-test", "version": "local"},
    "run_id": replay["run_id"],
    "observed_at": datetime.now(UTC).isoformat(),
    "assets": assets,
    "works": [
        {"observed_ref": work["id"], "title": work.get("title")}
        for work in manifest["works"]
    ],
    "variants": [
        {
            "observed_ref": variant["id"],
            "work_ref": variant["work_id"],
            "label": variant.get("label"),
        }
        for variant in manifest["variants"]
    ],
    "bundles": [
        {
            "observed_ref": bundle["id"],
            "variant_ref": bundle["variant_id"],
            "asset_refs": sorted(bundle_asset_refs[bundle["id"]]),
        }
        for bundle in manifest["bundles"]
    ],
}
observed_path.write_text(json.dumps(observed, indent=2, sort_keys=True), encoding="utf-8")
PY
}

validate_scenario() {
  local scenario="$1"
  run_cmd uv run chaos-librarian validate "$(scenario_path "$scenario")" --json
}

materialize_and_scan() {
  local scenario="$1"
  local out_dir="$RUN_ROOT/materialize-$scenario"

  section "materialize: $scenario"
  scan_tree "$scenario before materialize" "$out_dir/library"
  run_cmd uv run chaos-librarian materialize "$(scenario_path "$scenario")" \
    --out "$out_dir" --json
  scan_tree "$scenario after materialize" "$out_dir/library"
  run_cmd uv run chaos-librarian inspect "$out_dir" --json
}

wait_for_library() {
  local out_dir="$1"
  local deadline=$((SECONDS + 45))

  while [[ ! -d "$out_dir/library" ]]; do
    if ! child_is_running; then
      return 2
    fi
    if ((SECONDS >= deadline)); then
      return 3
    fi
    sleep 0.1
  done
}

run_wall_clock_with_scans() {
  local scenario="$1"
  local duration="$2"
  local speed="$3"
  local out_dir="$RUN_ROOT/run-$scenario"
  local command_log="$out_dir.command.log"
  local wait_status=0
  shift 3

  section "wall-clock run: $scenario"
  printf '$ uv run chaos-librarian run %q --out %q --duration %q --speed %q --json\n' \
    "$(scenario_path "$scenario")" "$out_dir" "$duration" "$speed"
  uv run chaos-librarian run "$(scenario_path "$scenario")" --out "$out_dir" \
    --duration "$duration" --speed "$speed" --json >"$command_log" 2>&1 &
  ACTIVE_CHILD="$!"

  wait_for_library "$out_dir" || wait_status="$?"
  if [[ "$wait_status" -eq 2 ]]; then
    finish_wall_clock_command "$scenario" "$command_log"
  elif [[ "$wait_status" -eq 3 ]]; then
    fail_wall_clock_timeout "$scenario" "$command_log" "$out_dir"
  fi
  scan_tree "$scenario baseline" "$out_dir/library"
  for interval in "$@"; do
    sleep "$interval"
    scan_tree "$scenario after ${interval}s interval" "$out_dir/library"
  done

  finish_wall_clock_command "$scenario" "$command_log"
  scan_tree "$scenario final" "$out_dir/library"
  run_cmd uv run chaos-librarian inspect "$out_dir" --json
}

section "functional test setup"
printf 'repo: %s\n' "$REPO_ROOT"
printf 'output: %s\n' "$RUN_ROOT"
printf 'log: %s\n' "$LOG_PATH"
printf 'started_utc: %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

section "capabilities"
CAPABILITIES_JSON="$RUN_ROOT/capabilities.json"
printf '$ uv run chaos-librarian capabilities --json\n'
uv run chaos-librarian capabilities --json | tee "$CAPABILITIES_JSON"
read -r READY_STATIC READY_FILESYSTEM READY_MEDIA < <(parse_capabilities "$CAPABILITIES_JSON")
printf 'ready_for.materialize_static: %s\n' "$READY_STATIC"
printf 'ready_for.materialize_filesystem_mutations: %s\n' "$READY_FILESYSTEM"
printf 'ready_for.materialize_media_mutations: %s\n' "$READY_MEDIA"

if [[ "$READY_STATIC" != "true" || "$READY_FILESYSTEM" != "true" ]]; then
  printf 'ffmpeg/ffprobe readiness is required for this functional test.\n' >&2
  exit 4
fi

section "validate scenario corpus subset"
validate_scenario active-library-churn
validate_scenario duplicate-variant-expanded
validate_scenario slow-copy-materialize
validate_scenario interceptor-catalog-run
if [[ "$READY_MEDIA" == "true" ]]; then
  validate_scenario version-evolution
  validate_scenario subtitle-ops-on-mp4
  validate_scenario embed-extract-roundtrip
  validate_scenario malformed-container-header
  validate_scenario negative-oracle-hash
  validate_scenario interceptor-catalog
else
  printf 'media mutation scenarios skipped; materialize_media_mutations is false.\n'
fi

section "plan, step, replay, compare"
PLAN_DIR="$RUN_ROOT/plan-active-library-churn"
REPLAY_DIR="$RUN_ROOT/replay-active-library-churn"
OBSERVED_JSON="$RUN_ROOT/observed-active-library-churn.json"
run_cmd uv run chaos-librarian plan "$(scenario_path active-library-churn)" \
  --out "$PLAN_DIR" --steps 3 --json
scan_tree "active-library-churn plan artifacts after --steps 3" "$PLAN_DIR"
run_cmd uv run chaos-librarian step "$PLAN_DIR" --next 3 --json
scan_tree "active-library-churn plan artifacts after step --next 3" "$PLAN_DIR"
run_cmd uv run chaos-librarian inspect "$PLAN_DIR" --json
run_cmd uv run chaos-librarian step "$PLAN_DIR" --next 1 --json
scan_tree "active-library-churn plan artifacts after final step" "$PLAN_DIR"
run_cmd uv run chaos-librarian inspect "$PLAN_DIR" --json
run_cmd uv run chaos-librarian replay "$PLAN_DIR/replay.json" --out "$REPLAY_DIR" \
  --against "$PLAN_DIR" --json
write_observed_from_fixture "$PLAN_DIR" "$OBSERVED_JSON"
run_cmd uv run chaos-librarian compare "$PLAN_DIR" "$OBSERVED_JSON" \
  --mode final-state --json

section "materialize enabled mutation fixtures"
materialize_and_scan duplicate-variant-expanded
materialize_and_scan slow-copy-materialize
if [[ "$READY_MEDIA" == "true" ]]; then
  materialize_and_scan active-library-churn
  materialize_and_scan version-evolution
  materialize_and_scan subtitle-ops-on-mp4
  materialize_and_scan embed-extract-roundtrip
  materialize_and_scan malformed-container-header
  materialize_and_scan negative-oracle-hash
  materialize_and_scan interceptor-catalog
else
  printf 'media mutation materialization skipped; materialize_media_mutations is false.\n'
fi

section "wall-clock mutation scans"
run_wall_clock_with_scans slow-copy-materialize 5s 1x 0.5 1 1 1 1
run_wall_clock_with_scans interceptor-catalog-run 8s 1x 0.5 1 1 1 1 1 1 1
SLOW_COPY_RUN_DIR="$RUN_ROOT/run-slow-copy-materialize"
SLOW_COPY_REPLAY_DIR="$RUN_ROOT/replay-slow-copy-materialize"
run_cmd uv run chaos-librarian replay "$SLOW_COPY_RUN_DIR/replay.json" \
  --out "$SLOW_COPY_REPLAY_DIR" --against "$SLOW_COPY_RUN_DIR" --json
printf 'network-lag replay skipped: replay does not support network_lag_start events.\n'

section "clean command"
CLEAN_TARGET="$RUN_ROOT/clean-target"
run_cmd uv run chaos-librarian plan "$(scenario_path duplicate-variant-expanded)" \
  --out "$CLEAN_TARGET" --json
scan_tree "clean target before clean" "$CLEAN_TARGET"
run_cmd uv run chaos-librarian clean "$CLEAN_TARGET" --json
scan_tree "clean target after clean" "$CLEAN_TARGET"

section "functional test complete"
printf 'finished_utc: %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
printf 'output: %s\n' "$RUN_ROOT"
printf 'log: %s\n' "$LOG_PATH"
