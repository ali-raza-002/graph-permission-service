from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class TupleKey(_Model):
    object: str
    relation: str
    user: str

    @classmethod
    def parse(cls, raw: str) -> TupleKey:
        """Build a key from 'type:id#relation@subject' notation."""
        obj, hash_, rest = raw.partition("#")
        relation, at, user = rest.partition("@")
        if not at or not hash_:
            raise ValueError(f"'{raw}' is not in 'type:id#relation@subject' notation")
        return cls(object=obj, relation=relation, user=user)

    def __str__(self) -> str:
        return f"{self.object}#{self.relation}@{self.user}"


type TupleLike = TupleKey | str


def as_key(value: TupleLike) -> TupleKey:
    return value if isinstance(value, TupleKey) else TupleKey.parse(value)


class ConsistencyMode(StrEnum):
    MINIMIZE_LATENCY = "minimize_latency"
    AT_LEAST_AS_FRESH = "at_least_as_fresh"
    AT_EXACT_SNAPSHOT = "at_exact_snapshot"
    FULLY_CONSISTENT = "fully_consistent"


class Consistency(_Model):
    mode: ConsistencyMode = ConsistencyMode.MINIMIZE_LATENCY
    token: str | None = None

    @classmethod
    def at_least_as_fresh(cls, token: str) -> Consistency:
        return cls(mode=ConsistencyMode.AT_LEAST_AS_FRESH, token=token)

    @classmethod
    def snapshot(cls, token: str) -> Consistency:
        return cls(mode=ConsistencyMode.AT_EXACT_SNAPSHOT, token=token)

    @classmethod
    def full(cls) -> Consistency:
        return cls(mode=ConsistencyMode.FULLY_CONSISTENT)


class Store(_Model):
    id: str
    name: str
    revision: int
    created_at: datetime
    updated_at: datetime


class AuthorizationModel(_Model):
    id: str
    store_id: str
    version: int
    schema_version: str
    created_at: datetime
    dsl: str | None = None


class WriteResult(_Model):
    revision: int
    consistency_token: str
    model_id: str
    written: int
    deleted: int


class StoredTuple(_Model):
    id: int
    object: str
    relation: str
    user: str
    created_revision: int
    created_at: datetime

    @property
    def key(self) -> TupleKey:
        return TupleKey(object=self.object, relation=self.relation, user=self.user)


class TuplePage(_Model):
    items: list[StoredTuple]
    next_cursor: str | None = None
    revision: int


type TraceKind = Literal[
    "check",
    "direct",
    "computed",
    "tuple_to_userset",
    "union",
    "intersection",
    "exclusion",
    "tuple",
    "cycle",
]
type ExpandKind = Literal[
    "userset",
    "ref",
    "direct",
    "computed",
    "tuple_to_userset",
    "union",
    "intersection",
    "exclusion",
    "subject",
]


class TraceNode(_Model):
    kind: TraceKind
    label: str
    result: Literal["allowed", "denied", "skipped"]
    object: str | None = None
    relation: str | None = None
    tuple_key: str | None = None
    role: Literal["base", "subtract"] | None = None
    cached: bool = False
    memoized: bool = False
    duration_ms: float | None = None
    children: list[TraceNode] = Field(default_factory=list)


class Resolution(_Model):
    model_id: str
    revision: int
    consistency_token: str
    duration_ms: float


class CheckResult(Resolution):
    allowed: bool
    decision_id: str
    cached: bool
    trace: TraceNode


class BatchCheckItem(_Model):
    correlation_id: str | None
    tuple_key: TupleKey
    allowed: bool
    decision_id: str | None = None
    error: str | None = None
    error_code: str | None = None


class BatchCheckResult(Resolution):
    results: list[BatchCheckItem]


class ExpandNode(_Model):
    kind: ExpandKind
    label: str
    object: str | None = None
    relation: str | None = None
    subject: str | None = None
    children: list[ExpandNode] = Field(default_factory=list)


class ExpandResult(Resolution):
    tree: ExpandNode


class ListObjectsResult(Resolution):
    objects: list[str]
    truncated: bool = False
    decision_id: str

    @property
    def ids(self) -> list[str]:
        """Object ids without the type prefix."""
        return [o.split(":", 1)[1] for o in self.objects]


class ListUsersResult(Resolution):
    users: list[str]
    truncated: bool = False
    decision_id: str


class ErrorPayload(_Model):
    code: str
    message: str
    details: list[dict[str, Any]] = Field(default_factory=list)
