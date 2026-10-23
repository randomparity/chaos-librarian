"""Scenario-bundle emission for the ``import`` command (issue #105 / ADR 0012).

``plan_staging`` applies file-level caps deterministically (sorted-path
order, observable skip reasons); ``apply_work_caps`` trims works/variants;
``emit_import_bundle`` stages the content-addressed media bundle, builds
the scenario payload, dumps YAML, re-validates through the full pipeline,
and rolls back exactly its own writes on any failure.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ruamel.yaml import YAML

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.importer.probe_input import ProbedInput
from chaos_librarian.importer.scan import SkipRecord
from chaos_librarian.importer.topology import ImportedWork, sanitize
from chaos_librarian.validation.input import prepare_run_input_from_bytes
from chaos_librarian.validation.pipeline import run_validation

__all__ = [
    "ImportReport",
    "apply_work_caps",
    "compute_staging",
    "emit_import_bundle",
    "plan_staging",
]

_BUNDLE_DIR_NAME = "media"
_PLACEHOLDER_PREFIX = "__BUNDLE__#"


def _as_mapping(node: object) -> dict[str, object] | None:
    """Narrow to ``dict[str, object]`` (ty cannot refine a bare ``dict``)."""
    return cast("dict[str, object]", node) if isinstance(node, dict) else None


@dataclass(frozen=True, slots=True)
class ImportReport:
    """Structured result of one successful import."""

    scenario_path: str
    bundle_dir: str
    files_scanned: int
    files_imported: int
    files_skipped: list[dict[str, str]]
    works: dict[str, int]
    sidecars: dict[str, int]
    bundle_bytes: int
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario_path": self.scenario_path,
            "bundle_dir": self.bundle_dir,
            "files_scanned": self.files_scanned,
            "files_imported": self.files_imported,
            "files_skipped": self.files_skipped,
            "works": self.works,
            "sidecars": self.sidecars,
            "bundle_bytes": self.bundle_bytes,
            "warnings": self.warnings,
        }


def plan_staging(
    probed: list[ProbedInput],
    skips: list[SkipRecord],
    *,
    mode: str,
    max_works: int | None,
    max_duration_s: float | None,
) -> tuple[list[ProbedInput], list[SkipRecord]]:
    """File-level filtering in sorted-path order with observable reasons.

    Sample mode caps imports per detected container (counted pre-topology)
    at ``--max-works`` files per category; the duration cap drops long
    files. Dedup happens at staging time via content-addressed names.
    """
    all_skips = list(skips)
    accepted: list[ProbedInput] = []
    per_category: dict[str, int] = {}
    seen: set[str] = set()

    for item in sorted(probed, key=lambda i: i.scanned.path):
        container = item.scanned.path.suffix.lstrip(".").lower()
        if max_duration_s is not None and item.probed.duration_seconds > max_duration_s:
            all_skips.append(SkipRecord(path=item.scanned.path, reason="cap:max_duration_s"))
            continue
        if mode == "sample" and max_works is not None:
            count = per_category.get(container, 0)
            if count >= max_works:
                all_skips.append(SkipRecord(path=item.scanned.path, reason="cap:max_works_sample"))
                continue
            per_category[container] = count + 1
        if mode == "dedup" and item.sha256 in seen:
            all_skips.append(SkipRecord(path=item.scanned.path, reason="mode:duplicate"))
            continue
        seen.add(item.sha256)
        accepted.append(item)
    return accepted, all_skips


def apply_work_caps(
    works: list[ImportedWork],
    skips: list[SkipRecord],
    *,
    mode: str,
    max_works: int | None,
    max_variants: int,
) -> None:
    """Trim variants beyond ``max_variants`` and works beyond ``max_works``.

    Mutates works so emission matches the accepted set. Dropped assets get
    observable skip reasons: ``cap:max_variants`` for variant overflows and
    ``cap:max_works`` for whole-work drops.
    """
    del mode  # sample's per-file cap already ran in plan_staging
    for work in works:
        if work.kind == "movie" and len(work.asset_payloads) > max_variants:
            keep = work.asset_payloads[:max_variants]
            dropped = work.asset_payloads[max_variants:]
            _drop_assets(work, dropped, skips, reason="cap:max_variants")
            work.asset_payloads[:] = keep
            _trim_payload_to_assets(work)

    if max_works is not None:
        survivors: list[ImportedWork] = []
        kept = 0
        for work in works:
            if kept < max_works:
                survivors.append(work)
                kept += 1
                continue
            skips.extend(
                SkipRecord(path=path, reason="cap:max_works")
                for path in work.asset_sources.values()
            )
        works[:] = survivors


def _trim_payload_to_assets(work: ImportedWork) -> None:
    """Drop payload variants whose assets no longer exist on the work."""
    keep_ids = {str(a["id"]) for a in work.asset_payloads}
    variants = _variants_list(work.payload)
    work.payload["variants"] = [v for v in variants if _variant_asset_ids(v) & keep_ids]


def _as_mapping_list(node: object) -> list[dict[str, object]]:
    if not isinstance(node, list):
        return []
    return [cast("dict[str, object]", v) for v in node if isinstance(v, dict)]


def _variants_list(payload: dict[str, object]) -> list[dict[str, object]]:
    return _as_mapping_list(payload.get("variants"))


def _bundle_assets(variant: dict[str, object]) -> list[dict[str, object]]:
    bundle = _as_mapping(variant.get("bundle"))
    if bundle is None:
        return []
    return _as_mapping_list(bundle.get("assets", []))


def _variant_asset_ids(variant: dict[str, object]) -> set[str]:
    return {str(a["id"]) for a in _bundle_assets(variant)}


def _drop_assets(
    work: ImportedWork,
    dropped_assets: list[dict[str, object]],
    skips: list[SkipRecord],
    *,
    reason: str,
) -> None:
    ids = {str(a["id"]) for a in dropped_assets}
    for asset_id in ids:
        source = work.asset_sources.pop(asset_id, None)
        if source is not None:
            skips.append(SkipRecord(path=source, reason=reason))


def compute_staging(
    accepted: list[ProbedInput],
    works: list[ImportedWork],
) -> tuple[list[tuple[Path, Path]], set[str]]:
    """Stage pairs for exactly the digests surviving works, plus the set.

    Content-addressed names dedup naturally: two assets sharing content
    reference one bundle file.
    """
    referenced: set[str] = set()
    for work in works:
        for asset in work.asset_payloads:
            import_source = _as_mapping(asset.get("import_source"))
            assert import_source is not None
            placeholder = str(import_source["path"])
            assert placeholder.startswith(_PLACEHOLDER_PREFIX)
            referenced.add(placeholder.removeprefix(_PLACEHOLDER_PREFIX))

    staged: list[tuple[Path, Path]] = []
    seen: set[str] = set()
    for item in sorted(accepted, key=lambda i: i.scanned.path):
        if item.sha256 not in referenced or item.sha256 in seen:
            continue
        seen.add(item.sha256)
        container = item.scanned.path.suffix.lstrip(".").lower()
        staged.append((item.scanned.path, Path(f"{item.sha256}.{container}")))
    return staged, seen


def emit_import_bundle(
    input_dir: Path,
    out: Path,
    works: list[ImportedWork],
    staged: list[tuple[Path, Path]],
    skips: list[SkipRecord],
) -> ImportReport:
    """Stage ``media/``, write scenario.yaml, re-validate, report.

    ``out`` is the scenario.yaml FILE path (generate single-file precedent);
    the bundle directory is ``out.parent / media``. Rollback wraps BOTH the
    staging copy loop and everything after it: every file written during
    staging is tracked, and any failure — mid-staging I/O error or
    post-staging validation failure — removes ``out`` and exactly the
    tracked names (never a directory sweep; a sibling scenario's bundle may
    share ``media/``).
    """
    out_dir = out.parent
    bundle_dir = out_dir / _BUNDLE_DIR_NAME
    written_bundle_files: list[Path] = []
    digest_to_name: dict[str, str] = {dst.stem: dst.name for _, dst in staged}

    out_written = False
    bundle_dir.mkdir(parents=True, exist_ok=True)
    try:
        for source, dest_name in staged:
            dest = bundle_dir / dest_name.name
            try:
                handle = dest.open("xb")
            except FileExistsError:
                if dest.is_symlink() or not dest.is_file():
                    raise ValueError(f"bundle entry is not a regular file: {dest}") from None
                with dest.open("rb") as existing:
                    digest = hashlib.file_digest(existing, "sha256").hexdigest()
                if digest != dest_name.stem:
                    raise ValueError(
                        f"bundle entry does not match its content digest: {dest}"
                    ) from None
                continue
            written_bundle_files.append(dest)
            with handle, source.open("rb") as original:
                shutil.copyfileobj(original, handle)
            with dest.open("rb") as copied:
                digest = hashlib.file_digest(copied, "sha256").hexdigest()
            if digest != dest_name.stem:
                raise ValueError(f"import source changed while staging: {source}; retry import")

        _rewrite_bundle_paths(works, digest_to_name)
        events = [event for w in works for event in w.sidecar_events]
        payload = _build_payload(input_dir, works, events)
        yaml_bytes = _dump_yaml(payload)
        _atomic_write(out, yaml_bytes)
        out_written = True
        report = _build_report(out, bundle_dir, works, staged, skips)
    except Exception:
        for path in written_bundle_files:
            path.unlink(missing_ok=True)
        if out_written:
            out.unlink(missing_ok=True)
        raise
    return report


def _rewrite_bundle_paths(works: list[ImportedWork], digest_to_name: dict[str, str]) -> None:
    """Replace ``__BUNDLE__#<sha>`` placeholders with bundle-relative paths."""
    for work in works:
        for asset in work.asset_payloads:
            import_source = _as_mapping(asset.get("import_source"))
            assert import_source is not None
            placeholder = str(import_source["path"])
            sha256 = placeholder.removeprefix(_PLACEHOLDER_PREFIX)
            import_source["path"] = f"{_BUNDLE_DIR_NAME}/{digest_to_name[sha256]}"


def _build_payload(
    input_dir: Path,
    works: list[ImportedWork],
    events: list[dict[str, object]],
) -> dict[str, object]:
    root_path = sanitize(input_dir.name) or "imported"
    return {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": f"import-{input_dir.name}-{datetime.now(UTC):%Y%m%d%H%M}",
        "seed": 0,
        "duration_scale": "normal",
        "library": {"roots": [{"id": "main", "path": root_path}]},
        "movies": [w.payload for w in works if w.kind == "movie"],
        "series": [w.payload for w in works if w.kind == "series"],
        "artists": [w.payload for w in works if w.kind == "artist"],
        "timeline": sorted(events, key=lambda e: str(e["id"])),
    }


def _dump_yaml(payload: dict[str, object]) -> bytes:
    yaml = YAML(typ="rt")
    yaml.default_flow_style = False
    stream = io.StringIO()
    yaml.dump(payload, stream)
    return stream.getvalue().encode()


def _atomic_write(out: Path, data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, out)
    finally:
        temp_path.unlink(missing_ok=True)


def _build_report(
    out: Path,
    bundle_dir: Path,
    works: list[ImportedWork],
    staged: list[tuple[Path, Path]],
    skips: list[SkipRecord],
) -> ImportReport:
    run_input = prepare_run_input_from_bytes(raw_bytes=out.read_bytes(), source_label="<import>")
    report = run_validation(run_input)
    if not report.ok:
        issues = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise ValueError(f"emitted scenario failed validation: {issues}")

    imported_assets = sum(len(w.asset_payloads) for w in works)
    sidecars = {"subtitles": 0, "nfo": 0, "posters": 0}
    for event in (e for w in works for e in w.sidecar_events):
        kind = event["kind"]
        if kind == "subtitle":
            sidecars["subtitles"] += 1
        elif kind == "nfo":
            sidecars["nfo"] += 1
        else:
            sidecars["posters"] += 1
    return ImportReport(
        scenario_path=str(out),
        bundle_dir=str(bundle_dir),
        files_scanned=len(skips) + imported_assets + sum(sidecars.values()),
        files_imported=imported_assets,
        files_skipped=[{"path": str(s.path), "reason": s.reason} for s in skips],
        works={
            "movies": sum(1 for w in works if w.kind == "movie"),
            "series": sum(1 for w in works if w.kind == "series"),
            "artists": sum(1 for w in works if w.kind == "artist"),
        },
        sidecars=sidecars,
        bundle_bytes=sum((bundle_dir / dst).stat().st_size for _, dst in staged),
        warnings=[],
    )
