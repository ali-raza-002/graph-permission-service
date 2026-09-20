from __future__ import annotations

from pydantic import BaseModel, Field

from warden.core.consistency import Consistency
from warden.core.refs import ID_PATTERN, NAME_PATTERN
from warden.engine.expand import ExpandNode
from warden.engine.trace import TraceNode
from warden.tuples.schemas import TupleKey

_OBJECT = f"^{NAME_PATTERN}:{ID_PATTERN}$"
_NAME = f"^{NAME_PATTERN}$"
_USER_FILTER = f"^{NAME_PATTERN}(#{NAME_PATTERN})?$"


class QueryOptions(BaseModel):
    consistency: Consistency | None = Field(
        default=None, description="Defaults to minimize_latency."
    )
    model_id: str | None = Field(default=None, description="Defaults to the latest model.")


class ContextualQuery(QueryOptions):
    contextual_tuples: list[TupleKey] = Field(
        default_factory=list,
        description="Tuples that hold only for this request, e.g. derived from a session.",
    )


class ResolutionStats(BaseModel):
    dispatches: int
    memo_hits: int
    cache_hits: int
    queries: int


class ResolutionMeta(BaseModel):
    model_id: str
    revision: int
    consistency_token: str
    duration_ms: float


class CheckRequest(ContextualQuery):
    tuple_key: TupleKey
    explain: bool = Field(
        default=False,
        description="Bypass cached results so the trace contains the complete resolution tree.",
    )


class CheckResponse(ResolutionMeta):
    allowed: bool
    decision_id: str
    cached: bool
    trace: TraceNode
    stats: ResolutionStats


class BatchCheckItem(BaseModel):
    tuple_key: TupleKey
    correlation_id: str | None = Field(default=None, max_length=128)


class BatchCheckRequest(ContextualQuery):
    checks: list[BatchCheckItem] = Field(min_length=1)


class BatchCheckResult(BaseModel):
    correlation_id: str | None
    tuple_key: TupleKey
    allowed: bool
    decision_id: str | None = None
    error: str | None = Field(
        default=None, description="Why this item could not be decided. `allowed` is then false."
    )
    error_code: str | None = None


class BatchCheckResponse(ResolutionMeta):
    results: list[BatchCheckResult]


class ExpandRequest(QueryOptions):
    object: str = Field(pattern=_OBJECT)
    relation: str = Field(pattern=_NAME)


class ExpandResponse(ResolutionMeta):
    tree: ExpandNode


class ListObjectsRequest(ContextualQuery):
    object_type: str = Field(pattern=_NAME)
    relation: str = Field(pattern=_NAME)
    user: str = Field(min_length=3, max_length=400)
    limit: int | None = Field(default=None, ge=1)


class ListObjectsResponse(ResolutionMeta):
    objects: list[str]
    truncated: bool = Field(
        description="More objects may exist beyond the limit or the candidate cap."
    )
    decision_id: str


class ListUsersRequest(ContextualQuery):
    object: str = Field(pattern=_OBJECT)
    relation: str = Field(pattern=_NAME)
    user_type: str = Field(
        pattern=_USER_FILTER,
        description="Subject type such as 'user', or a userset 'group#member'.",
    )


class ListUsersResponse(ResolutionMeta):
    users: list[str]
    truncated: bool
    decision_id: str
