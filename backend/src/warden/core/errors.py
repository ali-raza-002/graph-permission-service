from __future__ import annotations

from typing import Any


class WardenError(Exception):
    """Base class for errors that map onto a stable API error code."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class NotFoundError(WardenError):
    status_code = 404
    code = "not_found"


class ConflictError(WardenError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(WardenError):
    status_code = 422
    code = "validation_failed"


class InvalidTupleError(WardenError):
    status_code = 422
    code = "invalid_tuple"


class PreconditionFailedError(WardenError):
    status_code = 409
    code = "precondition_failed"


class InvalidConsistencyTokenError(WardenError):
    status_code = 400
    code = "invalid_consistency_token"


class ResolutionTooComplexError(WardenError):
    status_code = 422
    code = "resolution_too_complex"


class AuthenticationError(WardenError):
    status_code = 401
    code = "unauthenticated"


class PermissionDeniedError(WardenError):
    status_code = 403
    code = "forbidden"


class SnapshotTooOldError(WardenError):
    status_code = 400
    code = "snapshot_too_old"


class ServiceUnavailableError(WardenError):
    status_code = 503
    code = "unavailable"


class DeadlineExceededError(WardenError):
    status_code = 503
    code = "deadline_exceeded"
