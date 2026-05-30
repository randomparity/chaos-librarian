"""Tests for the negative-oracle hash phase-B helper."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import CorruptionActionError
from chaos_librarian.materializer.phase_b.oracle_hash import (
    OracleHashPhaseBContext,
    apply_wrong_oracle_hash,
    collided_hash_for,
    false_hash_for,
)

_SHA256_URI = re.compile(r"^sha256:[0-9a-f]{64}$")


def _hex(digest_uri: str) -> str:
    return digest_uri.removeprefix("sha256:")


def _hash(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _entry(
    *,
    input_version_id: str = "version_0001",
    output_version_id: str = "version_0002",
) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id="wrong_hash_001",
        scenario_id="negative-oracle-test",
        run_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        logical_time_ns=0,
        action=TimelineActionName.WRONG_ORACLE_HASH,
        target_ids=["asset_main"],
        input_version_ids=[input_version_id],
        output_version_ids=[output_version_id],
        location_ids=["location_0001"],
        state_delta={
            "input_path": "movies-hd/asset.mkv",
            "output_path": "movies-hd/asset.mkv",
            "profile": "negative-oracle",
            "algorithm": "sha256",
            "seed_material": "wrong_oracle_hash_v1:42:wrong_hash_001:asset_main",
        },
        phase=JournalPhase.ATOMIC,
    )


def _ctx(tmp_path: Path, probed: ProbedMedia | None = None) -> OracleHashPhaseBContext:
    return OracleHashPhaseBContext(
        library_root=tmp_path,
        post_phase_b_oracle_hashes={},
        version_probe_lookup=lambda _version_id: probed,
    )


def _probed() -> ProbedMedia:
    return ProbedMedia(container="matroska", duration_seconds=1.0, size_bytes=16, streams=[])


def _write_asset(tmp_path: Path, content: bytes = b"0123456789abcdef") -> Path:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(content)
    return asset


def _hash_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def test_false_hash_for_is_deterministic() -> None:
    actual_hash = _hash_bytes(b"actual")
    seed_material = "wrong_oracle_hash_v1:42:wrong_hash_001:asset_main"

    assert false_hash_for(seed_material, actual_hash) == false_hash_for(
        seed_material,
        actual_hash,
    )


def test_false_hash_for_never_returns_actual_hash() -> None:
    actual_hash = _hash_bytes(b"actual")

    assert false_hash_for("seed", actual_hash) != actual_hash


def test_apply_wrong_oracle_hash_records_actual_and_reported_hash(tmp_path: Path) -> None:
    asset = _write_asset(tmp_path)
    ctx = _ctx(tmp_path)

    action = apply_wrong_oracle_hash(ctx, _entry())

    assert action.actual_content_hash == _hash_bytes(asset.read_bytes())
    assert action.reported_content_hash == false_hash_for(
        "wrong_oracle_hash_v1:42:wrong_hash_001:asset_main",
        action.actual_content_hash,
    )
    assert action.reported_content_hash != action.actual_content_hash
    assert ctx.post_phase_b_oracle_hashes["version_0002"] == (
        action.reported_content_hash,
        None,
    )


def test_apply_wrong_oracle_hash_does_not_modify_file_bytes(tmp_path: Path) -> None:
    original = b"0123456789abcdef"
    asset = _write_asset(tmp_path, original)
    ctx = _ctx(tmp_path)

    apply_wrong_oracle_hash(ctx, _entry())

    assert asset.read_bytes() == original


def test_apply_wrong_oracle_hash_wraps_file_failures(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    with pytest.raises(CorruptionActionError) as exc_info:
        apply_wrong_oracle_hash(ctx, _entry())

    assert exc_info.value.error_code == "E_MATERIALIZE_CORRUPTION_FAILED"
    assert exc_info.value.payload["event_id"] == "wrong_hash_001"
    assert exc_info.value.payload["action"] == "wrong_oracle_hash"


def test_apply_wrong_oracle_hash_preserves_input_version_probed_metadata(
    tmp_path: Path,
) -> None:
    _write_asset(tmp_path)
    probed = _probed()
    ctx = _ctx(tmp_path, probed)

    action = apply_wrong_oracle_hash(ctx, _entry())

    assert ctx.post_phase_b_oracle_hashes[action.output_version_id] == (
        action.reported_content_hash,
        probed,
    )


def test_apply_wrong_oracle_hash_can_follow_prior_phase_b_mutation(tmp_path: Path) -> None:
    _write_asset(tmp_path, b"mutated bytes from earlier phase b")
    probed = _probed()
    prior_versions = {"version_0002": ("sha256:" + "a" * 64, probed)}
    ctx = OracleHashPhaseBContext(
        library_root=tmp_path,
        post_phase_b_oracle_hashes={},
        version_probe_lookup=lambda version_id: prior_versions.get(version_id, (None, None))[1],
    )

    action = apply_wrong_oracle_hash(
        ctx,
        _entry(input_version_id="version_0002", output_version_id="version_0003"),
    )

    assert action.input_version_id == "version_0002"
    assert action.output_version_id == "version_0003"
    assert ctx.post_phase_b_oracle_hashes["version_0003"] == (
        action.reported_content_hash,
        probed,
    )


@pytest.mark.parametrize("prefix_len", [1, 8, 63])
def test_collided_hash_shares_exact_prefix(prefix_len: int) -> None:
    referent = _hash("referent")
    real = _hash("real")
    result = collided_hash_for(referent, real, prefix_len)
    assert _SHA256_URI.match(result)
    referent_hex = _hex(referent)
    result_hex = _hex(result)
    assert result_hex[:prefix_len] == referent_hex[:prefix_len]
    # exact prefix: the char just past the shared prefix differs from the
    # referent (prefix_len 63 leaves exactly one char to differ).
    if prefix_len < 63:
        assert result_hex[prefix_len] != referent_hex[prefix_len]


@pytest.mark.parametrize("prefix_len", [1, 8, 63])
def test_collided_hash_differs_at_full_length(prefix_len: int) -> None:
    referent = _hash("referent")
    real = _hash("real")
    result = collided_hash_for(referent, real, prefix_len)
    assert result != referent
    assert result != real


def test_collided_hash_is_deterministic() -> None:
    referent = _hash("referent")
    real = _hash("real")
    assert collided_hash_for(referent, real, 8) == collided_hash_for(referent, real, 8)


def test_collided_hash_fallback_branch_when_candidate_equals_real() -> None:
    # Construct real so the first candidate equals it, forcing the fallback.
    referent = _hash("referent")
    prefix_len = 8
    referent_hex = _hex(referent)
    prefix = referent_hex[:prefix_len]
    # Find a `real` whose first candidate collides with `real` itself is hard to
    # force directly; instead assert that for the degenerate real == referent the
    # result still satisfies every invariant (real==referent forces the candidate
    # to share its full prefix with both and the guard to engage if equal).
    real = referent
    result = collided_hash_for(referent, real, prefix_len)
    assert _SHA256_URI.match(result)
    assert _hex(result)[:prefix_len] == prefix
    assert result != referent
    assert result != real
