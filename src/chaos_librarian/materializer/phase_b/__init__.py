"""Shared phase-B state, dispatch, and failure helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest, ProbedMedia
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    FilesystemAction,
    MaterializationFailure,
    MediaAction,
    NetworkLagAction,
    OracleHashAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.scenario import Asset, Scenario, TimelineActionName
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
)
from chaos_librarian.materializer.manifest_build import (
    augment_timeline_sidecars,
    augment_updated_sidecars,
    augment_versions,
)
from chaos_librarian.materializer.phase_b.corruption import (
    CorruptionPhaseBContext,
    apply_corruption_action,
    make_corruption_phase_b_context,
    supports_corruption_action,
)
from chaos_librarian.materializer.phase_b.filesystem import (
    FilesystemPhaseBContext,
    apply_filesystem_action,
    make_filesystem_phase_b_context,
    supports_filesystem_action,
)
from chaos_librarian.materializer.phase_b.media import (
    MediaPhaseBContext,
    apply_media_action,
    make_media_phase_b_context,
    supports_media_action,
)
from chaos_librarian.materializer.phase_b.oracle_hash import (
    OracleHashPhaseBContext,
    apply_wrong_oracle_hash,
    make_oracle_hash_phase_b_context,
    supports_oracle_hash_action,
)
from chaos_librarian.topology import iter_asset_contexts

PhaseBError = FilesystemActionError | MediaActionError | CorruptionActionError


@dataclass(slots=True)
class PhaseBState:
    """Mutable state accumulated while applying phase-B journal entries."""

    fs_ctx: FilesystemPhaseBContext
    media_ctx: MediaPhaseBContext
    corruption_ctx: CorruptionPhaseBContext
    oracle_hash_ctx: OracleHashPhaseBContext
    filesystem_actions: list[FilesystemAction] = field(default_factory=list)
    media_actions: list[MediaAction] = field(default_factory=list)
    corruption_actions: list[CorruptionAction] = field(default_factory=list)
    oracle_hash_actions: list[OracleHashAction] = field(default_factory=list)
    network_lag_actions: list[NetworkLagAction] = field(default_factory=list)


def make_phase_b_state(
    *,
    library_root: Path,
    scenario: Scenario,
    resolved_seed: int,
    ffmpeg_version: str,
    ffprobe_version: str,
    invocations: list[ToolInvocation],
    manifest: Manifest,
    initial_manifest: Manifest,
) -> PhaseBState:
    """Build shared phase-B dispatch state for materialize, run, and replay.

    ``manifest`` is the manifest at the end of the journal window (used for
    version-probe fallbacks). ``initial_manifest`` is the manifest at the start
    of the window; its sidecars seed the live sidecar registry so
    ``update_sidecar`` can resolve a sidecar that the journal later removes
    (issue #112).
    """
    scenario_assets = _index_assets(scenario)
    media_ctx = make_media_phase_b_context(
        library_root=library_root,
        scenario_assets=scenario_assets,
        resolved_seed=resolved_seed,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        invocations=invocations,
        initial_sidecars=initial_manifest.sidecars,
    )
    corruption_ctx = make_corruption_phase_b_context(
        library_root=library_root,
        resolved_seed=resolved_seed,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        invocations=invocations,
    )
    oracle_hashes: dict[str, tuple[str, ProbedMedia | None]] = {}
    manifest_probes = {version.id: version.probed for version in manifest.versions}

    def version_probe_lookup(version_id: str) -> ProbedMedia | None:
        entry = oracle_hashes.get(version_id)
        if entry is not None:
            return entry[1]
        entry = corruption_ctx.post_phase_b_versions.get(version_id)
        if entry is not None:
            return entry[1]
        entry = media_ctx.post_phase_b_versions.get(version_id)
        if entry is not None:
            return entry[1]
        return manifest_probes.get(version_id)

    return PhaseBState(
        fs_ctx=make_filesystem_phase_b_context(
            library_root=library_root,
            scenario_assets=scenario_assets,
            resolved_seed=resolved_seed,
        ),
        media_ctx=media_ctx,
        corruption_ctx=corruption_ctx,
        oracle_hash_ctx=make_oracle_hash_phase_b_context(
            library_root=library_root,
            post_phase_b_oracle_hashes=oracle_hashes,
            version_probe_lookup=version_probe_lookup,
        ),
    )


def dispatch_phase_b_entry(state: PhaseBState, entry: JournalEntry) -> None:
    """Apply one ordinary phase-B journal entry and append its audit action."""
    action = TimelineActionName(entry.action)
    if supports_filesystem_action(action):
        fs_action = apply_filesystem_action(state.fs_ctx, entry)
        if fs_action is not None:
            state.filesystem_actions.append(fs_action)
        return
    if supports_media_action(action):
        state.media_actions.append(apply_media_action(state.media_ctx, entry))
        return
    if supports_corruption_action(action):
        state.corruption_actions.append(apply_corruption_action(state.corruption_ctx, entry))
        return
    if supports_oracle_hash_action(action):
        state.oracle_hash_actions.append(apply_wrong_oracle_hash(state.oracle_hash_ctx, entry))
        return
    raise MediaActionError(
        f"unsupported phase-B action {action.value!r}",
        event_id=entry.event_id,
        action=action,
        cause=RuntimeError("not in phase-B dispatch sets"),
    )


def augment_phase_b_outputs(manifest: Manifest, state: PhaseBState) -> None:
    """Drain phase-B content evidence into the manifest."""
    augment_timeline_sidecars(manifest, state.fs_ctx.phase_b_sidecar_hashes)
    augment_versions(manifest, _version_evidence(state))
    augment_updated_sidecars(manifest, state.media_ctx.post_phase_b_sidecars)


def _version_evidence(state: PhaseBState) -> dict[str, tuple[str, ProbedMedia | None]]:
    versions: dict[str, tuple[str, ProbedMedia | None]] = {}
    versions.update(state.media_ctx.post_phase_b_versions)
    versions.update(state.corruption_ctx.post_phase_b_versions)
    versions.update(state.oracle_hash_ctx.post_phase_b_oracle_hashes)
    return versions


def phase_b_failure_outcome(exc: PhaseBError) -> Outcome:
    """Return the materialization outcome for a phase-B exception."""
    if isinstance(exc, MediaActionError):
        return Outcome.MEDIA_FAILED
    if isinstance(exc, CorruptionActionError):
        return Outcome.CORRUPTION_FAILED
    return Outcome.FS_FAILED


def phase_b_failure_record(exc: PhaseBError) -> MaterializationFailure:
    """Build the report failure row for a phase-B exception."""
    if isinstance(exc, MediaActionError):
        stage = FailureStage.MEDIA
        invocation_index = exc.tool_invocation_index
    elif isinstance(exc, CorruptionActionError):
        stage = FailureStage.CORRUPTION
        invocation_index = exc.tool_invocation_index
    else:
        stage = FailureStage.FILESYSTEM
        invocation_index = None
    cause = getattr(exc, "cause", None)
    return MaterializationFailure(
        asset_id=exc.asset_id,
        stage=stage,
        exit_code=None,
        stderr_tail=str(cause) if cause is not None else "",
        invocation_index=invocation_index,
    )


def _index_assets(scenario: Scenario) -> dict[str, Asset]:
    out: dict[str, Asset] = {}
    for context in iter_asset_contexts(scenario):
        out[context.asset.id] = context.asset
    return out
