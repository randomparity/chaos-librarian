"""Adapter input errors for fixture and observed-state loading."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from chaos_librarian.errors import ChaosLibrarianError

E_ADAPTER_FIXTURE_INVALID: Final = "E_ADAPTER_FIXTURE_INVALID"
E_ADAPTER_OBSERVED_INVALID: Final = "E_ADAPTER_OBSERVED_INVALID"
E_ADAPTER_RUN_ID_MISMATCH: Final = "E_ADAPTER_RUN_ID_MISMATCH"


class AdapterInputError(ChaosLibrarianError):
    """Raised when adapter inputs are malformed or internally inconsistent."""

    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = dict(details or {})
