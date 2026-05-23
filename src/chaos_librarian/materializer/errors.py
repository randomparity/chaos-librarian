"""Exception hierarchy raised by the materializer.

Every concrete subclass carries an ``error_code`` class attribute matching
the spec's error model. The CLI handler dispatches on subclass identity
and reads ``error_code`` / ``asset_id`` / ``field`` / ``payload`` into the
stdout JSON.
"""

from __future__ import annotations

from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.errors import ChaosLibrarianError


class MaterializationError(ChaosLibrarianError):
    """Base for every materializer-raised error.

    ``error_code`` is a class attribute set on each concrete subclass.
    """

    error_code: str = "E_MATERIALIZE_UNKNOWN"

    def __init__(
        self,
        message: str,
        *,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
        content_sources: tuple[ContentSourceEvidence, ...] = (),
    ) -> None:
        super().__init__(message)
        self.message = message
        self.asset_id = asset_id
        self.field = field
        self.payload: dict[str, object] = dict(payload or {})
        self.content_sources = content_sources


class TimelineUnsupportedError(MaterializationError):
    """Scenario has a non-empty timeline."""

    error_code: str = "E_MATERIALIZE_TIMELINE_UNSUPPORTED"


class UnsupportedMaterializationError(MaterializationError):
    """Container/codec/resolution/channels combination outside the supported matrix."""

    error_code: str = "E_MATERIALIZE_UNSUPPORTED"


class ToolFailedError(MaterializationError):
    """ffmpeg subprocess exited non-zero."""

    error_code: str = "E_MATERIALIZE_TOOL_FAILED"

    def __init__(
        self,
        message: str,
        *,
        invocation: ToolInvocation,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
        content_sources: tuple[ContentSourceEvidence, ...] = (),
    ) -> None:
        super().__init__(
            message,
            asset_id=asset_id,
            field=field,
            payload=payload,
            content_sources=content_sources,
        )
        self.invocation = invocation


class ProbeParseError(MaterializationError):
    """ffprobe stdout could not be parsed into ProbedMedia."""

    error_code: str = "E_MATERIALIZE_PROBE_PARSE_FAILED"


class FilesystemActionError(MaterializationError):
    """A phase-B helper raised; library/ must be wiped.

    ``cause`` is typed ``BaseException`` rather than ``OSError`` so the
    dispatcher can wrap contract-drift bugs (e.g. ``KeyError`` from a
    handler looking up an asset that isn't in the scenario) into the
    same structured exit-5 payload the CLI emits for syscall failures.
    ``errno`` is populated only when ``cause`` is an ``OSError``; for
    non-OSError causes it is ``None``.
    """

    error_code: str = "E_MATERIALIZE_FS_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        cause: BaseException,
        action: TimelineActionName,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload: dict[str, object] = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        merged_payload.setdefault("errno", cause.errno if isinstance(cause, OSError) else None)
        super().__init__(message, asset_id=asset_id, field=field, payload=merged_payload)
        self.event_id = event_id
        self.cause = cause
        self.action = action


class MediaActionError(MaterializationError):
    """A phase-B media handler (ffmpeg-backed or sidecar-regeneration) raised.

    Library/ must be wiped; materialization.json records
    outcome=media_failed. ``tool_invocation_index`` cross-refs the
    failing invocation in MaterializationReport.invocations when an
    ffmpeg call was involved; ``None`` for update_sidecar's pure-Python
    paths.
    """

    error_code: str = "E_MATERIALIZE_MEDIA_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        action: TimelineActionName,
        cause: BaseException,
        asset_id: str | None = None,
        tool_invocation_index: int | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload: dict[str, object] = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        merged_payload.setdefault("tool_invocation_index", tool_invocation_index)
        super().__init__(
            message,
            asset_id=asset_id,
            field=field,
            payload=merged_payload,
        )
        self.event_id = event_id
        self.cause = cause
        self.action = action
        self.tool_invocation_index = tool_invocation_index


class CorruptionActionError(MaterializationError):
    """A phase-B intentional corruption handler failed."""

    error_code: str = "E_MATERIALIZE_CORRUPTION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        action: TimelineActionName,
        cause: BaseException,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload: dict[str, object] = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        super().__init__(message, asset_id=asset_id, field=field, payload=merged_payload)
        self.event_id = event_id
        self.cause = cause
        self.action = action


class ContainmentViolationError(MaterializationError):
    """A scenario path resolved outside ``<run-dir>/library/``."""

    error_code: str = "E_PATH_CONTAINMENT"


class CapabilityGateError(MaterializationError):
    """ffmpeg or ffprobe missing or below minimum at materialize startup."""

    error_code: str = "E_MATERIALIZE_CAPABILITY_GATE"


class ScenarioValidationError(MaterializationError):
    """Scenario passed YAML parse but failed semantic validation.

    Raised by the orchestrator's pre-allocation gate so the materialize
    entry mirrors ``plan``'s validate-before-act behavior. The CLI handler
    dispatches this to exit 3, matching ``plan``'s convention.
    """

    error_code: str = "E_MATERIALIZE_VALIDATION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        validation_report: ValidationReport,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            message,
            asset_id=asset_id,
            field=field,
            payload=payload,
        )
        self.validation_report = validation_report
