"""FastAPI integration.

Example::

    guard = WardenGuard(client=get_warden, subject=current_subject)
    can_edit = guard.require("editor", "document", "document_id")

    @router.patch("/documents/{document_id}")
    async def update(document_id: str, decision: CheckResult = Depends(can_edit)) -> ...
"""

# Postponed annotations are deliberately not enabled here: FastAPI resolves the
# dependency signature at runtime and it refers to per-guard closures.

import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status

from warden_sdk.client import WardenClient
from warden_sdk.errors import WardenError
from warden_sdk.models import CheckResult

type Provider[T] = Callable[..., T] | Callable[..., Awaitable[T]]

# Warden's object id syntax. A path value outside it names nothing Warden could hold a
# relationship for, so it is answered here instead of surfacing Warden's 422 as an outage.
_OBJECT_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_\-.@|+=/:]{0,255}$")


class WardenGuard:
    def __init__(
        self,
        *,
        client: Provider[WardenClient],
        subject: Provider[str],
        on_error_status: int = status.HTTP_503_SERVICE_UNAVAILABLE,
    ) -> None:
        """`client` and `subject` are ordinary FastAPI dependencies, so they can use the
        request, other dependencies or app state to produce the Warden client and the
        caller's subject (e.g. 'user:anne')."""
        self._client = client
        self._subject = subject
        self._error_status = on_error_status

    def require(
        self, relation: str, object_type: str, param: str = "id"
    ) -> Callable[..., Awaitable[CheckResult]]:
        """Dependency that allows the request only if the caller has `relation` on
        `object_type:<path param>`. Denials become 403 with the decision id attached."""
        error_status = self._error_status

        async def dependency(
            request: Request,
            client: Annotated[WardenClient, Depends(self._client)],
            subject: Annotated[str, Depends(self._subject)],
        ) -> CheckResult:
            object_id = request.path_params.get(param)
            if object_id is None:
                raise RuntimeError(f"route has no path parameter named '{param}'")
            if not _OBJECT_ID.match(object_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "not_found", "message": f"no {object_type} '{object_id}'"},
                )
            obj = f"{object_type}:{object_id}"
            try:
                result = await client.check(obj, relation, subject)
            except WardenError as exc:
                raise HTTPException(
                    status_code=error_status,
                    detail={"code": "authorization_unavailable", "message": exc.message},
                ) from exc
            if not result.allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=_denial(obj, relation, subject, result),
                )
            return result

        dependency.__name__ = f"require_{relation}_on_{object_type}"
        return dependency


def _denial(obj: str, relation: str, subject: str, result: CheckResult) -> dict[str, Any]:
    return {
        "code": "forbidden",
        "message": f"{subject} lacks '{relation}' on {obj}",
        "decision_id": result.decision_id,
    }
