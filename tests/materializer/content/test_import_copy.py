"""Phase-A copy-path tests for import assets (issue #105 / ADR 0012).

Why: an import asset's library file must be a byte-identical copy of the
scenario-bundled original — no synthesis — with recorded evidence and a
real probe. Escape, missing-file, and no-scenario-dir cases fail loud with
``E_IMPORT_SOURCE_MISSING``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.materializer.test_capability_gates import _capabilities

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentTrackKind,
)
from chaos_librarian.contract.manifest import StreamKind
from chaos_librarian.engine.plan import run_plan
from chaos_librarian.materializer.content.synthesis import (
    PhaseAInputs,
    materialize_assets_phase_a,
)
from chaos_librarian.materializer.errors import ImportSourceMissingError
from chaos_librarian.materializer.tooling.probe import ProbedMedia, ProbedStream
from chaos_librarian.validation import run_validation
from chaos_librarian.validation.input import prepare_run_input_from_bytes

SCENARIO_YAML = """schema_version: 35
scenario_id: import-copy-test
seed: 1
duration_scale: short
library:
  roots:
    - id: movies
      path: movies
movies:
  - id: movie_imp
    title: Imported
    layout: movie_flat
    variants:
      - id: variant_imp
        label: default
        bundle:
          id: bundle_imp
          assets:
            - id: imp_1
              role: main
              container: mkv
              duration_seconds: 0.5
              import_source:
                path: {source_rel}
series: []
artists: []
timeline: []
"""


def _prepare(yaml_text: str):
    return prepare_run_input_from_bytes(
        raw_bytes=yaml_text.encode(), source_label="test:import-copy.yaml"
    )


def _artifacts(run_input):
    validation_report = run_validation(run_input)
    return run_plan(run_input=run_input, validation_report=validation_report)


def _phase_a(run_input, out_dir: Path, *, scenario_dir: Path | None) -> PhaseAInputs:
    return PhaseAInputs(
        scenario=run_input.scenario,
        out_dir=out_dir,
        artifacts=_artifacts(run_input),
        caps=_capabilities(),
        stamp_manifest=True,
        scenario_dir=scenario_dir,
    )


def test_copy_import_asset_copies_bytes_and_records_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scenario-dir" / "media" / "imp-1.mkv"
    source.parent.mkdir(parents=True, exist_ok=True)
    payload = b"original-bytes-0123456789"
    source.write_bytes(payload)

    probed = ProbedMedia(
        container="mkv",
        duration_seconds=0.5,
        size_bytes=len(payload),
        streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
    )
    monkeypatch.setattr(
        "chaos_librarian.materializer.content.synthesis.probe_file",
        lambda _path, *, self_contained_only: probed if self_contained_only else None,
    )

    result = materialize_assets_phase_a(
        _phase_a(
            _prepare(SCENARIO_YAML.format(source_rel="media/imp-1.mkv")),
            tmp_path / "out",
            scenario_dir=tmp_path / "scenario-dir",
        )
    )

    copied = tmp_path / "out" / "library" / "movies" / "Imported - default.mkv"
    assert copied.read_bytes() == payload

    (evidence,) = result.content_sources
    assert evidence.provider == "import-file"
    assert evidence.track_kind is ContentTrackKind.VIDEO
    assert evidence.cache_disposition is CacheDisposition.NOT_CACHEABLE
    assert evidence.origin_uri == "media/imp-1.mkv"
    content_hash = evidence.content_hash
    assert isinstance(content_hash, str)
    assert content_hash.startswith("sha256:")
    assert evidence.recipe_digest == content_hash

    (invocation,) = [i for i in result.invocations if i.tool == "import_copy"]
    assert invocation.exit_code == 0

    materialized = result.materialized_assets[0]
    assert materialized.size_bytes == probed.size_bytes
    assert materialized.duration_seconds == 0.5


def test_copy_import_asset_rejects_escape(tmp_path: Path) -> None:
    escape_dir = tmp_path / "outside"
    escape_dir.mkdir()
    (escape_dir / "x.mkv").write_bytes(b"x")
    with pytest.raises(ImportSourceMissingError):
        materialize_assets_phase_a(
            _phase_a(
                _prepare(SCENARIO_YAML.format(source_rel="../outside/x.mkv")),
                tmp_path / "out",
                scenario_dir=tmp_path / "scenario-dir",
            )
        )


def test_copy_import_asset_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ImportSourceMissingError) as exc_info:
        materialize_assets_phase_a(
            _phase_a(
                _prepare(SCENARIO_YAML.format(source_rel="media/gone.mkv")),
                tmp_path / "out",
                scenario_dir=tmp_path / "scenario-dir",
            )
        )
    assert exc_info.value.error_code == "E_IMPORT_SOURCE_MISSING"


def test_copy_import_asset_without_scenario_dir(tmp_path: Path) -> None:
    with pytest.raises(ImportSourceMissingError):
        materialize_assets_phase_a(
            _phase_a(
                _prepare(SCENARIO_YAML.format(source_rel="media/imp-1.mkv")),
                tmp_path / "out",
                scenario_dir=None,
            )
        )
