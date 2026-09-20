from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from warden.core.refs import NAME_PATTERN, RefParseError, RelationTuple


class TupleKey(BaseModel):
    """A relationship tuple in API notation, e.g. document:roadmap#viewer@user:anne."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [{"object": "document:roadmap", "relation": "viewer", "user": "user:anne"}]
        },
    )

    object: str = Field(min_length=3, max_length=330, description="Object as 'type:id'.")
    relation: str = Field(pattern=f"^{NAME_PATTERN}$")
    user: str = Field(
        min_length=3,
        max_length=400,
        description="Subject as 'type:id', 'type:*' or a userset 'type:id#relation'.",
    )

    @model_validator(mode="after")
    def _parse(self) -> TupleKey:
        try:
            RelationTuple.of(self.object, self.relation, self.user)
        except RefParseError as exc:
            raise ValueError(str(exc)) from None
        return self

    def to_tuple(self) -> RelationTuple:
        return RelationTuple.of(self.object, self.relation, self.user)

    @classmethod
    def from_tuple(cls, t: RelationTuple) -> TupleKey:
        return cls(object=str(t.object), relation=t.relation, user=str(t.subject))


class Precondition(BaseModel):
    tuple_key: TupleKey
    must_exist: bool = Field(
        description="True requires the tuple to exist, false requires it to be absent."
    )


class WriteCommand(BaseModel):
    writes: list[TupleKey] = Field(default_factory=list)
    deletes: list[TupleKey] = Field(default_factory=list)
    preconditions: list[Precondition] = Field(default_factory=list)
    on_duplicate: Literal["error", "ignore"] = "error"
    on_missing: Literal["error", "ignore"] = "error"
    model_id: str | None = Field(
        default=None, description="Model to validate writes against. Defaults to the latest."
    )


class WriteResult(BaseModel):
    revision: int
    consistency_token: str
    model_id: str
    written: int
    deleted: int


class StoredTuple(BaseModel):
    id: int
    object: str
    relation: str
    user: str
    created_revision: int
    created_at: datetime


class TupleChange(BaseModel):
    operation: Literal["write", "delete"]
    revision: int
    tuple_key: TupleKey


class TupleFilter(BaseModel):
    object_type: str | None = None
    object_id: str | None = None
    relation: str | None = None
    user: str | None = Field(default=None, description="Exact subject, e.g. user:anne")
