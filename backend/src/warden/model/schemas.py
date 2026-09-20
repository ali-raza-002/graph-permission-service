from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from warden.dsl.ast import AuthorizationModel


class Store(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ModelSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    store_id: str
    version: int
    schema_version: str
    created_at: datetime


class ModelDetail(ModelSummary):
    dsl: str
    ast: AuthorizationModel = Field(description="Typed AST compiled from the DSL source.")
