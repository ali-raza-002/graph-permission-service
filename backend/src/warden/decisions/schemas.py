from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from warden.engine.trace import TraceNode

DecisionKind = Literal["check", "list_objects", "list_users"]


class DecisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    store_id: str
    model_id: str
    revision: int
    kind: DecisionKind
    object: str
    relation: str
    subject: str
    allowed: bool | None
    result_count: int | None
    duration_ms: float
    cached: bool
    contextual_tuples: int
    api_key_id: str | None
    created_at: datetime


class Decision(DecisionSummary):
    trace: TraceNode | None = None


class TimelineBucket(BaseModel):
    bucket: datetime
    allowed: int
    denied: int


class DecisionStats(BaseModel):
    window_hours: int
    total: int = Field(description="Checks in the window. List queries are counted separately.")
    allowed: int
    denied: int
    list_queries: int
    allow_rate: float
    p50_ms: float
    p95_ms: float
    cached_rate: float
    timeline: list[TimelineBucket]
