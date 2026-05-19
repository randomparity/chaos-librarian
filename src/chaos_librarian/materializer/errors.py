"""Exception hierarchy raised by the materializer.

Every concrete subclass carries an ``error_code`` class attribute matching
the spec's error model. The CLI handler dispatches on subclass identity
and reads ``error_code`` / ``asset_id`` / ``field`` / ``payload`` into the
stdout JSON.
"""

from __future__ import annotations

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.validation import ValidationReport


class MaterializationError(Exception):
    """Base for every materializer-raised error.

    ``error_code`` is declared as a class-level default so subclasses can
    override it with a more specific code while still allowing the
    constructor to install an instance-level override (used by callers
    that need to attach a sub-code without subclassing).
    """

    error_code: str = "E_MATERIALIZE_UNKNOWN"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code
        self.message = message
        self.asset_id = asset_id
        self.field = field
        self.payload: dict[str, object] = dict(payload or {})


class TimelineUnsupportedError(MaterializationError):
    """Scenario has a non-empty timeline — Sprint 5 rejects."""

    error_code: str = "E_MATERIALIZE_TIMELINE_UNSUPPORTED"


class UnsupportedMaterializationError(MaterializationError):
    """Container/codec/resolution/channels combination outside Sprint 5 matrix."""

    error_code: str = "E_MATERIALIZE_UNSUPPORTED"


class ToolFailedError(MaterializationError):
    """ffmpeg subprocess exited non-zero."""

    error_code: str = "E_MATERIALIZE_TOOL_FAILED"

    def __init__(
        self,
        message: str,
        *,
        invocation: ToolInvocation,
        error_code: str | None = None,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            asset_id=asset_id,
            field=field,
            payload=payload,
        )
        self.invocation = invocation


class ProbeParseError(MaterializationError):
    """ffprobe stdout could not be parsed into ProbedMedia."""

    error_code: str = "E_MATERIALIZE_PROBE_PARSE_FAILED"


class ContainmentViolationError(MaterializationError):
    """A scenario path resolved outside ``<run-dir>/library/``."""

    error_code: str = "E_PATH_CONTAINMENT"


class CapabilityGateError(MaterializationError):
    """ffmpeg or ffprobe missing or below minimum at materialize startup."""

    error_code: str = "E_MATERIALIZE_CAPABILITY_GATE"


class ScenarioValidationError(MaterializationError):
    """Scenario passed YAML parse but failed semantic validation.

    Raised by the orchestrator's pre-allocation gate (Finding 1) so the
    materialize entry mirrors ``plan``'s validate-before-act behavior. The
    CLI handler dispatches this to exit 3, matching ``plan``'s convention.
    """

    error_code: str = "E_MATERIALIZE_VALIDATION_FAILED"

    def __init__(
        self,
        message: str,
        *,
        validation_report: ValidationReport,
        error_code: str | None = None,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            asset_id=asset_id,
            field=field,
            payload=payload,
        )
        self.validation_report = validation_report
