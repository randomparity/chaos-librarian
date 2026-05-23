"""Shared phase-B state, dispatch, and failure helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest, ManifestSidecar
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    FilesystemAction,
    MaterializationFailure,
    MediaAction,
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

PhaseBError = FilesystemActionError | MediaActionError | CorruptionActionError


@dataclass(slots=True)
class PhaseBState:
    """Mutable state accumulated while applying phase-B journal entries."""

    fs_ctx: FilesystemPhaseBContext
    media_ctx: MediaPhaseBContext
    corruption_ctx: CorruptionPhaseBContext
    filesystem_actions: list[FilesystemAction] = field(default_factory=list)
    media_actions: list[MediaAction] = field(default_factory=list)
    corruption_actions: list[CorruptionAction] = field(default_factory=list)


def make_phase_b_state(
    *,
    library_root: Path,
    scenario: Scenario,
    resolved_seed: int,
    ffmpeg_version: str,
    ffprobe_version: str,
    invocations: list[ToolInvocation],
    manifest: Manifest,
) -> PhaseBState:
    """Build shared phase-B dispatch state for materialize, run, and replay."""
    scenario_assets = _index_assets(scenario)
    return PhaseBState(
        fs_ctx=make_filesystem_phase_b_context(
            library_root=library_root,
            scenario_assets=scenario_assets,
            resolved_seed=resolved_seed,
        ),
        media_ctx=make_media_phase_b_context(
            library_root=library_root,
            scenario_assets=scenario_assets,
            resolved_seed=resolved_seed,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            invocations=invocations,
            sidecar_lookup=_sidecar_lookup_from(manifest),
        ),
        corruption_ctx=make_corruption_phase_b_context(
            library_root=library_root,
            resolved_seed=resolved_seed,
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
    raise MediaActionError(
        f"unsupported phase-B action {action.value!r}",
        event_id=entry.event_id,
        action=action,
        cause=RuntimeError("not in phase-B dispatch sets"),
    )


def augment_phase_b_outputs(manifest: Manifest, state: PhaseBState) -> None:
    """Drain phase-B content evidence into the manifest."""
    augment_timeline_sidecars(manifest, state.fs_ctx.phase_b_sidecar_hashes)
    augment_versions(manifest, state.media_ctx.post_phase_b_versions)
    augment_versions(manifest, state.corruption_ctx.post_phase_b_versions)
    augment_updated_sidecars(manifest, state.media_ctx.post_phase_b_sidecars)


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
        invocation_index = None
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
    for work in scenario.works:
        for variant in work.variants:
            for asset in variant.bundle.assets:
                out[asset.id] = asset
    return out


def _sidecar_lookup_from(manifest: Manifest) -> Callable[[str], ManifestSidecar | None]:
    by_id = {sidecar.id: sidecar for sidecar in manifest.sidecars}

    def lookup(sidecar_id: str) -> ManifestSidecar | None:
        return by_id.get(sidecar_id)

    return lookup
