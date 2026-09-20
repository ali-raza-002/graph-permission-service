from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TraceKind = Literal[
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
TraceResult = Literal["allowed", "denied", "skipped"]


class TraceNode(BaseModel):
    """One step of a check resolution, forming the tree the console renders as a graph."""

    kind: TraceKind
    label: str
    result: TraceResult
    object: str | None = None
    relation: str | None = None
    tuple_key: str | None = None
    role: Literal["base", "subtract"] | None = None
    cached: bool = Field(default=False, description="Answered from the shared check cache.")
    memoized: bool = Field(
        default=False,
        description="A repeat of a sub-problem already resolved in this request; its full "
        "trace appears where it was first resolved.",
    )
    duration_ms: float | None = None
    children: list[TraceNode] = Field(default_factory=list)


def skipped(label: str) -> TraceNode:
    return TraceNode(kind="check", label=label, result="skipped")


def prune(node: TraceNode, max_nodes: int) -> TraceNode:
    """Copy of the tree with at most max_nodes nodes, used before persisting traces.

    Allowed branches are kept first so a truncated trace still explains a grant.
    """
    budget = [max_nodes - 1]

    def copy(n: TraceNode) -> TraceNode:
        ordered = sorted(n.children, key=lambda c: c.result != "allowed")
        kept: list[TraceNode] = []
        for child in ordered:
            if budget[0] <= 0:
                break
            budget[0] -= 1
            kept.append(child)
        return n.model_copy(update={"children": [copy(c) for c in kept]})

    return copy(node)


def count_nodes(node: TraceNode) -> int:
    return 1 + sum(count_nodes(c) for c in node.children)
