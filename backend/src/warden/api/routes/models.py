from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from warden.api.deps import ContainerDep, Cursor, PageSize, require
from warden.auth.keys import Principal, Scope
from warden.core.pagination import DEFAULT_PAGE_SIZE, Page, decode_int_cursor
from warden.dsl import DslIssue, ModelCompileError, format_model, parse_model, validate_model
from warden.dsl.ast import AuthorizationModel
from warden.model.schemas import ModelDetail, ModelSummary

router = APIRouter(tags=["models"])

_MAX_DSL = 200_000


class DslSource(BaseModel):
    dsl: str = Field(max_length=_MAX_DSL)


class ValidationResult(BaseModel):
    valid: bool
    issues: list[DslIssue]
    ast: AuthorizationModel | None = None
    formatted: str | None = None


@router.post("/v1/dsl/validate")
async def validate_dsl(
    body: DslSource, _: Annotated[Principal, Depends(require(Scope.MODELS_READ))]
) -> ValidationResult:
    """Parse and validate DSL without saving it. Used for live editor diagnostics."""
    try:
        model = parse_model(body.dsl)
    except ModelCompileError as exc:
        return ValidationResult(valid=False, issues=exc.issues)
    issues = validate_model(model)
    valid = not any(i.severity == "error" for i in issues)
    return ValidationResult(
        valid=valid,
        issues=issues,
        ast=model if valid else None,
        formatted=format_model(model) if valid else None,
    )


@router.post("/v1/stores/{store_id}/models", status_code=status.HTTP_201_CREATED)
async def write_model(
    store_id: str,
    body: DslSource,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.MODELS_WRITE))],
) -> ModelDetail:
    return await container.models.write(store_id, body.dsl)


@router.get("/v1/stores/{store_id}/models")
async def list_models(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.MODELS_READ))],
    limit: PageSize = DEFAULT_PAGE_SIZE,
    cursor: Cursor = None,
) -> Page[ModelSummary]:
    await container.stores.ensure_exists(store_id)
    return await container.models.page(store_id, limit=limit, cursor=decode_int_cursor(cursor))


@router.get("/v1/stores/{store_id}/models/latest")
async def latest_model(
    store_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.MODELS_READ))],
) -> ModelDetail:
    return await container.models.latest(store_id)


@router.get("/v1/stores/{store_id}/models/{model_id}")
async def get_model(
    store_id: str,
    model_id: str,
    container: ContainerDep,
    _: Annotated[Principal, Depends(require(Scope.MODELS_READ))],
) -> ModelDetail:
    return await container.models.get(store_id, model_id)
