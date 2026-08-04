"""Tests for loading Chaos Librarian oracle fixtures into the adapter."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, TypeAdapter

from chaos_librarian.adapter import fixture as fixture_module
from chaos_librarian.adapter.errors import E_ADAPTER_FIXTURE_INVALID, AdapterInputError
from chaos_librarian.adapter.fixture import load_fixture
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.replay_bundle import ReplayBundle
from chaos_librarian.contract.reports import AssetReport
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.errors import ChaosLibrarianError
from tests.support.adapter import scenario_bytes as _scenario_bytes
from tests.support.adapter import write_plan_fixture as _write_plan_fixture

_REPLAY_ADAPTER: TypeAdapter[ReplayBundle] = TypeAdapter(ReplayBundle)
_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


def _rewrite_json_model(path: Path, model: BaseModel) -> None:
    path.write_text(_canonical_json(model))


def _canonical_json(model: BaseModel) -> str:
    return model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"


def _load_replay(run_dir: Path) -> ReplayBundle:
    return _REPLAY_ADAPTER.validate_json((run_dir / "replay.json").read_text())


def _write_replay(run_dir: Path, replay: ReplayBundle) -> None:
    _rewrite_json_model(run_dir / "replay.json", replay)


def _journal(run_dir: Path) -> list[JournalEntry]:
    return [
        _JOURNAL_ADAPTER.validate_json(line)
        for line in (run_dir / "journal.jsonl").read_text().splitlines()
        if line.strip()
    ]


def _write_journal(run_dir: Path, entries: list[JournalEntry]) -> None:
    (run_dir / "journal.jsonl").write_bytes(serialize_journal_bytes(entries))


def _fixture_invalid_error(run_dir: Path) -> AdapterInputError:
    with pytest.raises(AdapterInputError) as exc_info:
        load_fixture(run_dir)
    assert exc_info.value.error_code == E_ADAPTER_FIXTURE_INVALID
    return exc_info.value


def _assert_fixture_invalid(run_dir: Path) -> None:
    _fixture_invalid_error(run_dir)


def test_load_fixture_reads_required_artifacts(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)

    fixture = load_fixture(run_dir)

    assert fixture.run_dir == run_dir
    assert fixture.run_id == fixture.replay_bundle.run_id
    assert fixture.scenario_id == "identity-move-rename"
    assert fixture.initial_manifest.assets
    assert fixture.current_manifest.assets
    assert fixture.journal
    assert fixture.reports.assets


def test_load_fixture_rejects_missing_reports_directory(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    reports_dir = run_dir / "reports"
    for path in sorted(reports_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    reports_dir.rmdir()

    error = _fixture_invalid_error(run_dir)

    assert error.message == "reports directory is required"
    assert error.details["path"] == str(reports_dir)


def test_load_fixture_rejects_missing_sentinel(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    (run_dir / ".chaos-librarian-run").unlink()

    with pytest.raises(ChaosLibrarianError) as exc_info:
        load_fixture(run_dir)
    assert exc_info.value.__class__.__name__ == "SentinelInvalidError"


def test_load_fixture_rejects_malformed_replay_json(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    (run_dir / "replay.json").write_text("{")

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_malformed_present_report(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    asset_report_path = next((run_dir / "reports" / "assets").glob("*.json"))
    asset_report_path.write_text('{"not": "an asset report"}')

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_sentinel_run_id_mismatch(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    fixture = load_fixture(run_dir)
    sentinel = fixture.sentinel.model_copy(update={"run_id": uuid.uuid4()})
    _rewrite_json_model(run_dir / ".chaos-librarian-run", sentinel)

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_journal_run_id_mismatch(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    entries = _journal(run_dir)
    entries[0] = entries[0].model_copy(update={"run_id": uuid.uuid4()})
    _write_journal(run_dir, entries)

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_mixed_journal_scenario_ids(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    entries = _journal(run_dir)
    entries[0] = entries[0].model_copy(update={"scenario_id": "different-scenario"})
    _write_journal(run_dir, entries)

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_scenario_yaml_replay_scenario_mismatch(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    (run_dir / "scenario.yaml").write_bytes(_scenario_bytes("static-library.yaml"))

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_plan_only_scenario_yaml_run_id_mismatch(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    replay = _load_replay(run_dir)
    changed_run_id = uuid.uuid4()
    _write_replay(run_dir, replay.model_copy(update={"run_id": changed_run_id}))
    sentinel = RunSentinel.model_validate_json((run_dir / ".chaos-librarian-run").read_text())
    sentinel = sentinel.model_copy(update={"run_id": changed_run_id})
    _rewrite_json_model(run_dir / ".chaos-librarian-run", sentinel)

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_journal_digest_mismatch(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    replay = _load_replay(run_dir)
    _write_replay(run_dir, replay.model_copy(update={"journal_digest": "0" * 64}))

    _assert_fixture_invalid(run_dir)


def test_load_fixture_uses_canonical_journal_serializer_for_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    replay = _load_replay(run_dir)
    canonical_bytes = b"canonical-journal-bytes\n"
    monkeypatch.setattr(fixture_module, "serialize_journal_bytes", lambda _: canonical_bytes)
    _write_replay(
        run_dir,
        replay.model_copy(update={"journal_digest": hashlib.sha256(canonical_bytes).hexdigest()}),
    )

    fixture = load_fixture(run_dir)

    assert fixture.replay_bundle.journal_digest == hashlib.sha256(canonical_bytes).hexdigest()


def test_load_fixture_accepts_run_mode_wall_clock_digest_normalization(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    entries = [
        entry.model_copy(update={"wall_clock_time": datetime(2026, 5, 22, tzinfo=UTC)})
        for entry in _journal(run_dir)
    ]
    _write_journal(run_dir, entries)
    replay = _load_replay(run_dir)
    digest_entries = [entry.model_copy(update={"wall_clock_time": None}) for entry in entries]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    replay_payload = replay.model_dump(mode="json")
    replay_payload.update(
        {
            "execution_mode": "run",
            "journal_digest": digest,
            "created_at": "2026-05-22T00:00:00Z",
            "toolchain": {"ffmpeg": "6.1", "ffprobe": "6.1", "mkvtoolnix": None},
            "content_sources": [],
        }
    )
    _write_replay(run_dir, _REPLAY_ADAPTER.validate_python(replay_payload))

    fixture = load_fixture(run_dir)

    assert fixture.replay_bundle.execution_mode == "run"


def test_load_fixture_rejects_report_filename_id_mismatch(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    asset_report_path = next((run_dir / "reports" / "assets").glob("*.json"))
    report = AssetReport.model_validate_json(asset_report_path.read_text())
    changed = report.model_copy(update={"asset_id": "different-asset"})
    _rewrite_json_model(asset_report_path, changed)

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_report_id_missing_from_manifest(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    asset_report_path = next((run_dir / "reports" / "assets").glob("*.json"))
    report = AssetReport.model_validate_json(asset_report_path.read_text())
    changed = report.model_copy(update={"asset_id": "missing-asset"})
    new_path = asset_report_path.with_name("missing-asset.json")
    asset_report_path.unlink()
    _rewrite_json_model(new_path, changed)

    _assert_fixture_invalid(run_dir)


def test_load_fixture_rejects_missing_asset_report_when_reports_present(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    next((run_dir / "reports" / "assets").glob("*.json")).unlink()
    _assert_fixture_invalid(run_dir)


@pytest.mark.parametrize(
    "directory_name",
    [
        "assets",
        "movies",
        "series",
        "seasons",
        "episodes",
        "artists",
        "albums",
        "discs",
        "tracks",
        "variants",
        "bundles",
    ],
)
def test_load_fixture_rejects_missing_report_family(
    tmp_path: Path,
    directory_name: str,
) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    reports_dir = run_dir / "reports" / directory_name
    reports = sorted(reports_dir.glob("*.json"))
    for report in reports:
        report.unlink()
    reports_dir.rmdir()

    error = _fixture_invalid_error(run_dir)

    assert error.details["missing"] == [directory_name]
    assert error.details["extra"] == []


def test_load_fixture_rejects_old_work_report_directory(tmp_path: Path) -> None:
    run_dir = _write_plan_fixture(tmp_path)
    works_dir = run_dir / "reports" / "works"
    works_dir.mkdir()
    (works_dir / "work-a.json").write_text("{}")

    error = _fixture_invalid_error(run_dir)

    assert error.details["missing"] == []
    assert error.details["extra"] == ["works"]
