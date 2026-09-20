from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from warden_sdk.models import BatchCheckItem


class WardenError(Exception):
    """Raised for any non-2xx response from Warden."""

    def __init__(
        self, status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


class WardenAuthError(WardenError):
    pass


class WardenNotFoundError(WardenError):
    pass


class WardenConflictError(WardenError):
    pass


class WardenValidationError(WardenError):
    pass


class WardenUnavailableError(WardenError):
    pass


class WardenBatchCheckError(WardenError):
    """Some items of a batch check could not be decided (unknown relation, too complex)."""

    def __init__(self, failed: Mapping[str, BatchCheckItem]) -> None:
        summary = "; ".join(f"{cid}: {item.error}" for cid, item in list(failed.items())[:3])
        super().__init__(
            200,
            "batch_check_failed",
            f"{len(failed)} check(s) could not be decided: {summary}",
            [{"correlation_id": cid, "error": item.error} for cid, item in failed.items()],
        )
        self.failed = dict(failed)


def error_for(status: int) -> type[WardenError]:
    if status in {401, 403}:
        return WardenAuthError
    if status == 404:
        return WardenNotFoundError
    if status == 409:
        return WardenConflictError
    if status in {400, 422}:
        return WardenValidationError
    if status >= 500:
        return WardenUnavailableError
    return WardenError
