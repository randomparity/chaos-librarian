"""Cross-toolchain manifest canonicalization.

Strips fields that legitimately vary across ffmpeg/ffprobe builds so two
manifests produced by different toolchains compare equal on structure.

Stripped fields:
- ``versions[].content_hash``, ``versions[].probed``
- ``sidecars[].content_hash``

Plan-only equivalence (same toolchain, same seed) is byte-exact and
does NOT need canonicalization.
"""

from __future__ import annotations

from typing import Any

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializationReport,
    NetworkLagAction,
    OracleHashAction,
)
from chaos_librarian.contract.scenario import TimelineActionName


def canonicalize(manifest: Manifest) -> dict[str, Any]:
    """Return a dict suitable for == comparison across toolchains.

    The returned shape is a JSON-compatible dict (lists/dicts/primitives);
    callers should NOT round-trip it back through ``Manifest.model_validate``
    (the stripped fields would fail re-parse if a stricter schema requires
    them in the future).
    """
    manifest_payload = manifest.model_dump(mode="json", exclude_none=True)
    for version in manifest_payload.get("versions", []):
        version.pop("content_hash", None)
        version.pop("probed", None)
    for sidecar in manifest_payload.get("sidecars", []):
        sidecar.pop("content_hash", None)
    return manifest_payload


def corruption_evidence(manifest: Manifest, report: MaterializationReport) -> dict[str, Any]:
    """Return deterministic interceptor evidence for cross-toolchain comparison."""
    return {
        "manifest": canonicalize(manifest),
        "corruption_actions": [
            {
                "event_id": action.event_id,
                "target_asset_id": action.target_asset_id,
                "output_version_id": action.output_version_id,
                "corruptor": action.corruptor,
                "byte_start": action.byte_start,
                "byte_count": action.byte_count,
                "seed_material": action.seed_material,
            }
            for action in report.corruption_actions
        ],
        "oracle_hash_actions": [
            _oracle_hash_evidence(action) for action in report.oracle_hash_actions
        ],
        "filesystem_metadata_actions": [
            _touch_mtime_evidence(action)
            for action in report.filesystem_actions
            if action.action is TimelineActionName.TOUCH_MTIME
        ],
        "network_lag_actions": [
            _network_lag_evidence(action) for action in report.network_lag_actions
        ],
    }


def _oracle_hash_evidence(action: OracleHashAction) -> dict[str, Any]:
    return _compact(
        {
            "event_id": action.event_id,
            "action": action.action.value,
            "target_asset_id": action.target_asset_id,
            "input_path": action.input_path,
            "output_path": action.output_path,
            "input_version_id": action.input_version_id,
            "output_version_id": action.output_version_id,
            "seed_material": action.seed_material,
        }
    )


def _touch_mtime_evidence(action: FilesystemAction) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "event_id": action.event_id,
        "action": action.action.value,
        "target_asset_id": action.target_asset_id,
        "from_path": action.from_path,
        "to_path": action.to_path,
        "temp_path": action.temp_path,
    }
    if action.mtime_before_ns is not None and action.mtime_after_ns is not None:
        evidence["mtime_delta_ns"] = action.mtime_after_ns - action.mtime_before_ns
    return _compact(evidence)


def _network_lag_evidence(action: NetworkLagAction) -> dict[str, Any]:
    return _compact(
        {
            "event_id": action.event_id,
            "commit_event_id": action.commit_event_id,
            "effect": action.effect.value,
            "target_ref": action.target_ref,
            "after_event_id": action.after_event_id,
            "logical_start_ns": action.logical_start_ns,
            "logical_commit_ns": action.logical_commit_ns,
            "requested_duration_ns": action.requested_duration_ns,
            "from_path": action.from_path,
            "to_path": action.to_path,
            "provider": action.provider,
            "enforced": action.enforced,
        }
    )


def _compact(evidence: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in evidence.items() if value is not None}
