"""Matroska muxing-profile content-source evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import MatroskaMuxingProfile

MUXING_PROVIDER_NAME: Final = "builtin-mkvmerge"


@dataclass(frozen=True, slots=True)
class MuxingSourceRequest:
    asset_id: str
    seed: int
    container: str
    profile: MatroskaMuxingProfile


@dataclass(frozen=True, slots=True)
class MuxingSourceResolution:
    deterministic_seed: int
    evidence: ContentSourceEvidence


def resolve_muxing_source(request: MuxingSourceRequest) -> MuxingSourceResolution:
    """Resolve deterministic mkvmerge profile evidence."""
    deterministic_seed = _muxing_deterministic_seed(request)
    evidence = ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=ContentTrackKind.MUXING,
        source=request.profile.value,
        provider=MUXING_PROVIDER_NAME,
        recipe_digest=_muxing_recipe_digest(
            request=request,
            deterministic_seed=deterministic_seed,
        ),
        matroska_muxing_profile=request.profile,
        container=request.container,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )
    return MuxingSourceResolution(deterministic_seed=deterministic_seed, evidence=evidence)


def _muxing_deterministic_seed(request: MuxingSourceRequest) -> int:
    payload = {
        "asset_id": request.asset_id,
        "container": request.container,
        "profile": request.profile.value,
        "provider": MUXING_PROVIDER_NAME,
        "seed": request.seed,
    }
    return int(_sha256_hex(payload)[:8], 16)


def _muxing_recipe_digest(
    *,
    request: MuxingSourceRequest,
    deterministic_seed: int,
) -> str:
    payload = {
        "deterministic_seed": deterministic_seed,
        "provider": MUXING_PROVIDER_NAME,
        "request": {
            "asset_id": request.asset_id,
            "container": request.container,
            "profile": request.profile.value,
            "seed": request.seed,
            "track_kind": ContentTrackKind.MUXING.value,
        },
    }
    return f"sha256:{_sha256_hex(payload)}"


def _sha256_hex(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()
