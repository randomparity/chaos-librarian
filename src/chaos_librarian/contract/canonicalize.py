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
from chaos_librarian.contract.materialization import MaterializationReport


def canonicalize(manifest: Manifest) -> dict[str, Any]:
    """Return a dict suitable for == comparison across toolchains.

    The returned shape is a JSON-compatible dict (lists/dicts/primitives);
    callers should NOT round-trip it back through ``Manifest.model_validate``
    (the stripped fields would fail re-parse if a stricter schema requires
    them in the future).
    """
    blob = manifest.model_dump(mode="json", exclude_none=True)
    for version in blob.get("versions", []):
        version.pop("content_hash", None)
        version.pop("probed", None)
    for sidecar in blob.get("sidecars", []):
        sidecar.pop("content_hash", None)
    return blob


def corruption_evidence(manifest: Manifest, report: MaterializationReport) -> dict[str, Any]:
    """Return deterministic malformed-media evidence for cross-toolchain comparison."""
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
    }
