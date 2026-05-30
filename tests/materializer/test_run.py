"""Layer 3 — orchestrator with run_ffmpeg and probe_file mocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import (
    FailureStage,
    FilesystemAction,
    MaterializationReport,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer import run as run_mod
from chaos_librarian.materializer import synthesis as synthesis_mod
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    FilesystemActionError,
    ScenarioValidationError,
    ToolFailedError,
)
from chaos_librarian.materializer.phase_b import filesystem as filesystem_mod
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.validation import codes
from tests.materializer.audio_recipe_helpers import AUDIO_NOISE_SCENARIO

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
INVALID_FIXTURE_DIR = FIXTURE_DIR / "invalid"

_MKV_MUXING_PROFILE_SCENARIO = """schema_version: 30
scenario_id: muxing-profile-capability-test
seed: 138
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_mux
    title: Mux Profile
    layout: movie_flat
    variants:
      - id: variant_mux
        label: mkv
        bundle:
          id: bundle_mux
          assets:
            - id: asset_mux
              role: main
              container: mkv
              duration_seconds: 1.0
              matroska_muxing_profile: no_cues
              video:
                source: color_bars
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
"""

_WEBM_PROFILE_SCENARIO = """schema_version: 30
scenario_id: webm-capability-test
seed: 138
duration_scale: short
library:
  roots:
    - id: movies_hd
      path: movies-hd
movies:
  - id: movie_webm
    title: WebM Profile
    layout: movie_flat
    variants:
      - id: variant_webm
        label: webm
        bundle:
          id: bundle_webm
          assets:
            - id: asset_webm
              role: main
              container: webm
              duration_seconds: 1.0
              matroska_muxing_profile: short_clusters
              video:
                source: color_bars
                codec: vp9
                resolution: sd
series: []
artists: []
timeline: []
"""


@pytest.fixture(autouse=True)
def _patch_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """All Layer 3 tests assume capabilities pass; only behavior we care
    about is the orchestrator's own logic."""
    monkeypatch.setattr(run_mod, "detect_capabilities", _capabilities)


def _capabilities(
    *,
    materialize_hevc_video: bool = True,
    materialize_hdr_video: bool = True,
    materialize_resolution_switch_video: bool = True,
    materialize_audio_recipes: bool = True,
    materialize_matroska_muxing_profiles: bool = True,
    materialize_webm_video: bool = True,
) -> Capabilities:
    return Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
            materialize_hevc_video=materialize_hevc_video,
            materialize_hdr_video=materialize_hdr_video,
            materialize_resolution_switch_video=materialize_resolution_switch_video,
            materialize_audio_recipes=materialize_audio_recipes,
            materialize_matroska_muxing_profiles=materialize_matroska_muxing_profiles,
            materialize_webm_video=materialize_webm_video,
        ),
    )


def _patch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make run_ffmpeg + probe_file both succeed for every asset."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        output = Path(argv[-1])
        output.write_bytes(b"x")
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=0,
            duration_ns=1_000_000,
        )
        return invocation, ""

    def fake_probe(_path: Path) -> ProbedMedia:
        return ProbedMedia(
            container="matroska,webm",
            duration_seconds=1.0,
            size_bytes=1,
            streams=[
                ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480, fps=24.0)
            ],
        )

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(synthesis_mod, "probe_file", fake_probe)


def test_materialize_refuses_audio_noise_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        run_mod,
        "detect_capabilities",
        lambda: _capabilities(materialize_audio_recipes=False),
    )
    monkeypatch.setattr(
        synthesis_mod,
        "run_ffmpeg",
        lambda *_args, **_kwargs: pytest.fail("audio recipe gate should run before synthesis"),
    )
    scenario_path = tmp_path / "audio-noise.yaml"
    scenario_path.write_text(AUDIO_NOISE_SCENARIO, encoding="utf-8")
    out = tmp_path / "run-001"

    with pytest.raises(CapabilityGateError) as exc:
        materialize_scenario(scenario_path, out)

    assert exc.value.field == "ready_for.materialize_audio_recipes"
    assert exc.value.asset_id == "asset_noise"
    assert not out.exists()


@pytest.mark.parametrize(
    ("scenario_text", "capability_kwarg", "field", "asset_id"),
    [
        (
            _MKV_MUXING_PROFILE_SCENARIO,
            "materialize_matroska_muxing_profiles",
            "ready_for.materialize_matroska_muxing_profiles",
            "asset_mux",
        ),
        (
            _WEBM_PROFILE_SCENARIO,
            "materialize_webm_video",
            "ready_for.materialize_webm_video",
            "asset_webm",
        ),
    ],
)
def test_materialize_refuses_muxing_profile_capability_regressions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    scenario_text: str,
    capability_kwarg: str,
    field: str,
    asset_id: str,
) -> None:
    monkeypatch.setattr(
        run_mod,
        "detect_capabilities",
        lambda: _capabilities(**{capability_kwarg: False}),
    )
    monkeypatch.setattr(
        synthesis_mod,
        "run_ffmpeg",
        lambda *_args, **_kwargs: pytest.fail("muxing profile gate should run first"),
    )
    scenario_path = tmp_path / "profile.yaml"
    scenario_path.write_text(scenario_text, encoding="utf-8")
    out = tmp_path / "run-001"

    with pytest.raises(CapabilityGateError) as exc:
        materialize_scenario(scenario_path, out)

    assert exc.value.field == field
    assert exc.value.asset_id == asset_id
    assert not out.exists()


def test_materialize_filesystem_only_timeline_runs_phase_b(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 6 wires phase B into the orchestrator. The fixture
    moves then renames an asset, and the final on-disk layout must match
    the rename target. The report must record one ``FilesystemAction``
    per journal event that produced a disk change (2 events here)."""
    _patch_success(monkeypatch)
    out = tmp_path / "run-001"
    artifacts = materialize_scenario(FIXTURE_DIR / "identity-move-rename.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    library = out / "library"
    # Move places the asset under movies-hd/<title>.mkv; rename then
    # renames the file to movies-hd/Blazar.mkv (the fixture's final step).
    assert (library / "movies-hd" / "Blazar.mkv").exists()
    report = _load_materialization_report(out)
    assert len(report.filesystem_actions) == 2


def test_materialize_delete_then_add_file_restores_bytes_and_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: add_file restores a deleted asset, and materialize must use
    one UUID4 run_id across journal, replay bundle, sentinel, and report."""
    _patch_success(monkeypatch)
    scenario_path = tmp_path / "add-file.yaml"
    scenario_path.write_text(
        "schema_version: 30\n"
        "scenario_id: add-file-rejected\n"
        "seed: 11\n"
        "duration_scale: short\n"
        "library:\n"
        "  roots:\n"
        "    - id: movies_hd\n"
        "      path: movies-hd\n"
        "movies:\n"
        "  - id: movie_quasar\n"
        "    title: Synthetic Quasar\n"
        "    layout: movie_flat\n"
        "    variants:\n"
        "      - id: variant_hd\n"
        "        label: hd\n"
        "        bundle:\n"
        "          id: bundle_hd\n"
        "          assets:\n"
        "            - id: asset_main\n"
        "              role: primary_video\n"
        "              container: mkv\n"
        "              duration_seconds: 5\n"
        "              video:\n"
        "                source: color_bars\n"
        "                codec: h264\n"
        "                resolution: 1080p\n"
        "              audio:\n"
        "                - codec: aac\n"
        "                  channels: stereo\n"
        "                  language: eng\n"
        "series: []\n"
        "artists: []\n"
        "timeline:\n"
        "  - id: delete_001\n"
        "    at: 1s\n"
        "    action: delete_file\n"
        "    target: asset_main\n"
        "  - id: add_001\n"
        "    at: 2s\n"
        "    action: add_file\n"
        "    target: asset_main\n"
        "    to: movies-hd/new.mkv\n"
    )
    out = tmp_path / "run-001"
    artifacts = materialize_scenario(scenario_path, out)
    library = out / "library"
    assert not (library / "movies-hd" / "Synthetic Quasar - hd.mkv").exists()
    assert (library / "movies-hd" / "new.mkv").read_bytes() == b"x"
    assert artifacts.replay_bundle.run_id == artifacts.materialization_report.run_id

    run_id = str(artifacts.materialization_report.run_id)
    journal = [json.loads(line) for line in (out / "journal.jsonl").read_text().splitlines()]
    replay_payload = json.loads((out / "replay.json").read_text())
    report_payload = json.loads((out / "materialization.json").read_text())
    sentinel_payload = json.loads((out / ".chaos-librarian-run").read_text())
    assert {entry["run_id"] for entry in journal} == {run_id}
    assert replay_payload["run_id"] == run_id
    assert report_payload["run_id"] == run_id
    assert sentinel_payload["run_id"] == run_id


def test_materialize_phase_b_oserror_aborts_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: an OSError from a phase-B helper must wrap to
    ``FilesystemActionError`` and route through the fs_failed cleanup
    path: ``library/`` is wiped, the report records outcome=fs_failed,
    and a ``MaterializationFailure`` with stage=filesystem is recorded.
    The 3rd ``_move_asset`` call is patched to crash; the fixture emits
    two move-shaped journal entries, so the failure lands on the second
    one (event_id ``rename_001``)."""
    _patch_success(monkeypatch)
    call_count = {"n": 0}
    original = filesystem_mod._move_asset

    def crashing_move(
        ctx: filesystem_mod.FilesystemPhaseBContext, entry: JournalEntry
    ) -> FilesystemAction:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise OSError(2, "No such file or directory")
        return original(ctx, entry)

    monkeypatch.setattr(filesystem_mod, "_move_asset", crashing_move)
    # ``_DISPATCH`` captured a direct reference to ``_move_asset`` at module
    # import; replace both entries so dispatch picks up the crashing shim.
    monkeypatch.setitem(filesystem_mod._DISPATCH, TimelineActionName.MOVE_ASSET, crashing_move)
    monkeypatch.setitem(filesystem_mod._DISPATCH, TimelineActionName.RENAME_FILE, crashing_move)
    out = tmp_path / "run-001"
    with pytest.raises(FilesystemActionError):
        materialize_scenario(FIXTURE_DIR / "identity-move-rename.yaml", out)
    assert not (out / "library").exists()  # library/ wiped on cleanup
    report = _load_materialization_report(out)
    assert report.outcome is Outcome.FS_FAILED
    assert report.outcome is not Outcome.SUCCESS
    sentinel_payload = json.loads((out / ".chaos-librarian-run").read_text())
    assert sentinel_payload["state"] == "complete"
    assert any(f.stage is FailureStage.FILESYSTEM for f in report.failures)


def _load_materialization_report(out_dir: Path) -> MaterializationReport:
    """Load ``materialization.json`` and re-hydrate as a pydantic model.

    ``canonical_json`` strips ``None`` fields (``exclude_none=True``), so
    the on-disk payload omits ``exit_code`` / ``invocation_index`` for
    filesystem failures. Backfill them as ``None`` before validating so
    the round-trip succeeds without forcing the contract to declare
    defaults for fields that are conceptually required for ffmpeg-stage
    failures.
    """
    payload = json.loads((out_dir / "materialization.json").read_text())
    for failure in payload.get("failures", []):
        failure.setdefault("exit_code", None)
        failure.setdefault("invocation_index", None)
        failure.setdefault("asset_id", None)
    return MaterializationReport.model_validate(payload)


def test_orchestrator_refuses_unsupported_audio_codec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: unsupported static media now fails semantic validation before
    preflight; the run-dir must not be created."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "opus.yaml"
    scenario.write_text(_STATIC_SCENARIO_OPUS)
    out = tmp_path / "run"
    with pytest.raises(ScenarioValidationError) as exc:
        materialize_scenario(scenario, out)
    assert any(
        issue.code == codes.E_MATERIALIZE_UNSUPPORTED
        for issue in exc.value.validation_report.issues
    )
    assert not out.exists()


def test_orchestrator_refuses_hevc_when_encoder_capability_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: HEVC scenarios require libx265. The refusal must happen before
    run-dir allocation so callers do not get a half-created fixture."""
    monkeypatch.setattr(
        run_mod,
        "detect_capabilities",
        lambda: _capabilities(materialize_hevc_video=False),
    )

    out = tmp_path / "hevc-no-libx265"
    with pytest.raises(CapabilityGateError) as exc:
        materialize_scenario(FIXTURE_DIR / "hevc-mkv.yaml", out)

    assert exc.value.field == "ready_for.materialize_hevc_video"
    assert not out.exists()


def test_orchestrator_refuses_hdr_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: HDR scenarios require libx265 10-bit + setparams. The refusal
    must happen before run-dir allocation."""
    monkeypatch.setattr(
        run_mod,
        "detect_capabilities",
        lambda: _capabilities(materialize_hevc_video=True, materialize_hdr_video=False),
    )
    scenario = tmp_path / "hdr.yaml"
    scenario.write_text(
        (FIXTURE_DIR / "hevc-mkv.yaml")
        .read_text()
        .replace("resolution: sd", "resolution: sd\n                hdr_mode: hdr10")
    )

    out = tmp_path / "hdr-no-support"
    with pytest.raises(CapabilityGateError) as exc:
        materialize_scenario(scenario, out)

    assert exc.value.field == "ready_for.materialize_hdr_video"
    assert not out.exists()


def test_orchestrator_refuses_resolution_switch_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: sd_to_hd MPEG-TS requires libx264 support. The refusal must
    happen before run-dir allocation so callers do not get partial files."""
    monkeypatch.setattr(
        run_mod,
        "detect_capabilities",
        lambda: _capabilities(materialize_resolution_switch_video=False),
    )
    scenario = tmp_path / "resolution-switch.yaml"
    scenario.write_text(_RESOLUTION_SWITCH_SCENARIO)

    out = tmp_path / "resolution-switch-no-support"
    with pytest.raises(CapabilityGateError) as exc:
        materialize_scenario(scenario, out)

    assert exc.value.field == "ready_for.materialize_resolution_switch_video"
    assert not out.exists()


def test_orchestrator_records_ffmpeg_failure_and_wipes_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: a synthesis-time failure leaves a partial run-dir with the
    sentinel at state=complete (caught failure), library/ wiped, and
    materialization.json populated with the failure record."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=1,
            duration_ns=500_000,
        )
        return invocation, "ffmpeg simulated failure"

    def fail_probe(_path: Path) -> ProbedMedia:
        pytest.fail("probe should not be called")

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(synthesis_mod, "probe_file", fail_probe)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    with pytest.raises(ToolFailedError):
        materialize_scenario(scenario, out)
    assert out.exists()
    assert (out / ".chaos-librarian-run").exists()
    assert list((out / "library").iterdir()) == []
    materialization = (out / "materialization.json").read_text()
    assert '"outcome": "tool_failed"' in materialization
    report_payload = json.loads(materialization)
    replay_payload = json.loads((out / "replay.json").read_text())
    expected_sources = ["color_bars", "sine"]
    assert [item["source"] for item in report_payload["content_sources"]] == expected_sources
    assert [item["source"] for item in replay_payload["content_sources"]] == expected_sources
    assert {item["provider"] for item in report_payload["content_sources"]} == {"builtin-lavfi"}


def test_orchestrator_success_path_populates_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: the success path's contract is content_hash + probed populated
    for every asset version, and content_hash populated for every sidecar
    (Finding 3) in manifest.current.json."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    artifacts = materialize_scenario(scenario, out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    for version in artifacts.current_manifest.versions:
        assert version.content_hash is not None
        assert version.probed is not None
    assert artifacts.current_manifest.sidecars, (
        "_STATIC_SCENARIO declares a sidecar SRT; the manifest must reflect it"
    )
    for sidecar in artifacts.current_manifest.sidecars:
        assert sidecar.content_hash is not None
        assert sidecar.content_hash.startswith("sha256:")


def test_orchestrator_refuses_semantically_invalid_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 1 — Sprint 5 must not produce filesystem writes for
    scenarios that fail semantic validation (path containment, unsafe
    path components, etc.). The validation gate runs before any run-dir
    allocation. Any invalid fixture suffices; the gate's behavior is
    uniform across semantic-error codes."""
    _patch_success(monkeypatch)
    invalid = INVALID_FIXTURE_DIR / "path-escape.yaml"
    out = tmp_path / "must_not_exist"
    with pytest.raises(ScenarioValidationError) as exc:
        materialize_scenario(invalid, out)
    assert exc.value.validation_report.ok is False
    assert not out.exists()


def test_orchestrator_rejects_embedded_subtitle_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 2 — Sprint 5 supports sidecar-only; embedded lands in
    Sprint 7. Falling through silently would produce media missing the
    requested subtitles."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "embedded.yaml"
    scenario.write_text(_STATIC_SCENARIO_WITH_EMBEDDED_SUBS)
    out = tmp_path / "run"
    with pytest.raises(ScenarioValidationError) as exc:
        materialize_scenario(scenario, out)
    issue = next(
        issue
        for issue in exc.value.validation_report.issues
        if issue.code == codes.E_MATERIALIZE_UNSUPPORTED
    )
    assert issue.path is not None
    assert issue.path.endswith(".subtitles[0].mode")
    assert not out.exists()


def test_orchestrator_rejects_unsupported_subtitle_recipe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: validation must reject unsupported declared subtitle recipes before writes."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "ass.yaml"
    scenario.write_text(_STATIC_SCENARIO_WITH_ASS_SUBS)
    out = tmp_path / "run"
    with pytest.raises(ScenarioValidationError) as exc:
        materialize_scenario(scenario, out)
    issue = next(
        issue
        for issue in exc.value.validation_report.issues
        if issue.code == codes.E_MATERIALIZE_UNSUPPORTED
    )
    assert issue.path is not None
    assert issue.path.endswith(".subtitles[0].source")
    assert not out.exists()


def test_orchestrator_probes_each_asset_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 5 — re-probing wastes a subprocess per asset and
    (previously) used a run-dir-relative path that misresolved against
    the CLI cwd. Lock the call count and absolute-path invariant to
    catch a regression that re-introduces the second probe_file call."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        output = Path(argv[-1])
        output.write_bytes(b"x")
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=0,
            duration_ns=1_000_000,
        )
        return invocation, ""

    calls: list[Path] = []

    def counting_probe(path: Path) -> ProbedMedia:
        calls.append(path)
        return ProbedMedia(
            container="matroska,webm",
            duration_seconds=1.0,
            size_bytes=1,
            streams=[
                ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480, fps=24.0)
            ],
        )

    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(synthesis_mod, "probe_file", counting_probe)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    materialize_scenario(scenario, out)
    assert len(calls) == 1
    assert all(path.is_absolute() for path in calls)


_STATIC_SCENARIO = """\
schema_version: 30
scenario_id: static-test
seed: 1
duration_scale: short
library:
  roots:
    - id: r0
      path: library
movies:
  - id: movie_static
    title: Static
    layout: movie_flat
    variants:
      - id: va0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - codec: srt
                  language: eng
                  mode: sidecar
                  source: generated_srt
series: []
artists: []
timeline: []
"""

_RESOLUTION_SWITCH_SCENARIO = """\
schema_version: 30
scenario_id: resolution-switch-capability-test
seed: 133
duration_scale: short
library:
  roots:
    - id: r0
      path: library
movies:
  - id: movie_switch
    title: Resolution Switch
    layout: movie_flat
    variants:
      - id: variant_switch
        label: sd-to-hd
        bundle:
          id: bundle_switch
          assets:
            - id: asset_switch
              role: main
              container: ts
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: sd
                resolution_sequence: sd_to_hd
series: []
artists: []
timeline: []
"""

_STATIC_SCENARIO_OPUS = _STATIC_SCENARIO.replace("codec: aac", "codec: opus")

_STATIC_SCENARIO_WITH_EMBEDDED_SUBS = _STATIC_SCENARIO.replace(
    "mode: sidecar",
    "mode: embedded",
)

_STATIC_SCENARIO_WITH_ASS_SUBS = _STATIC_SCENARIO.replace(
    "codec: srt",
    "codec: ass",
)
