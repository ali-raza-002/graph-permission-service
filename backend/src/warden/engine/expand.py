"""Userset expansion: who holds a relation on an object, as a graph.

Each userset is expanded once. Later occurrences, including cycles, are emitted as
`ref` nodes pointing at the expanded one, so the result stays linear in the number of
reachable usersets even when the underlying relationships form a dense graph.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from warden.core.errors import ResolutionTooComplexError
from warden.core.refs import ObjectRef, SubjectRef
from warden.dsl.ast import (
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    Rewrite,
    TupleToUsersetNode,
    UnionNode,
)
from warden.dsl.printer import format_rewrite
from warden.dsl.typesystem import TypeSystem, restriction_allows
from warden.engine.reader import TupleReader

ExpandKind = Literal[
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


type _Userset = tuple[ObjectRef, str]


class ExpandNode(BaseModel):
    kind: ExpandKind
    label: str
    object: str | None = None
    relation: str | None = None
    subject: str | None = None
    children: list[ExpandNode] = Field(default_factory=list)


class Expander:
    def __init__(self, typesystem: TypeSystem, reader: TupleReader, *, max_depth: int = 25) -> None:
        self._ts = typesystem
        self._reader = reader
        self._max_depth = max_depth

    async def expand(self, obj: ObjectRef, relation: str) -> ExpandNode:
        return await self._expand(obj, relation, 0, set())

    async def _expand(
        self, obj: ObjectRef, relation: str, depth: int, started: set[_Userset]
    ) -> ExpandNode:
        key = (obj, relation)
        label = f"{obj}#{relation}"
        if key in started:
            return ExpandNode(kind="ref", label=label, object=str(obj), relation=relation)
        if depth >= self._max_depth:
            raise ResolutionTooComplexError(
                f"expansion exceeded the maximum depth of {self._max_depth} at {label}"
            )
        started.add(key)
        node = ExpandNode(kind="userset", label=label, object=str(obj), relation=relation)
        if not self._ts.has_relation(obj.type, relation):
            return node
        rewrite = self._ts.relation(obj.type, relation).rewrite
        node.children.append(await self._rewrite(rewrite, obj, relation, depth + 1, started))
        return node

    async def _rewrite(
        self, rewrite: Rewrite, obj: ObjectRef, relation: str, depth: int, started: set[_Userset]
    ) -> ExpandNode:
        label = format_rewrite(rewrite)
        match rewrite:
            case DirectNode(types=restrictions):
                subjects = [
                    s
                    for s in await self._reader.read_subjects(obj, relation)
                    if any(restriction_allows(r, s) for r in restrictions)
                ]
                leaves = [
                    ExpandNode(kind="subject", label=str(s), subject=str(s))
                    for s in subjects
                    if s.relation is None
                ]
                nested = await asyncio.gather(
                    *(
                        self._expand(s.as_object(), s.relation, depth, started)
                        for s in subjects
                        if s.relation is not None
                    )
                )
                return ExpandNode(kind="direct", label=label, children=[*leaves, *nested])
            case ComputedNode(relation=target):
                sub = await self._expand(obj, target, depth, started)
                return ExpandNode(kind="computed", label=label, relation=target, children=[sub])
            case TupleToUsersetNode(tupleset=tupleset, computed=computed):
                allowed_parents = self._ts.direct_restrictions(obj.type, tupleset)
                parents = [
                    p
                    for p in await self._reader.read_subjects(obj, tupleset)
                    if p.relation is None
                    and not p.is_wildcard
                    and any(restriction_allows(r, p) for r in allowed_parents)
                    and self._ts.has_relation(p.type, computed)
                ]
                expanded = await asyncio.gather(
                    *(self._expand(p.as_object(), computed, depth, started) for p in parents)
                )
                return ExpandNode(kind="tuple_to_userset", label=label, children=list(expanded))
            case UnionNode(children=children) | IntersectionNode(children=children):
                is_union = isinstance(rewrite, UnionNode)
                parts = await asyncio.gather(
                    *(self._rewrite(c, obj, relation, depth, started) for c in children)
                )
                return ExpandNode(
                    kind="union" if is_union else "intersection",
                    label="or" if is_union else "and",
                    children=list(parts),
                )
            case ExclusionNode(base=base, subtract=subtract):
                base_part, subtract_part = await asyncio.gather(
                    self._rewrite(base, obj, relation, depth, started),
                    self._rewrite(subtract, obj, relation, depth, started),
                )
                return ExpandNode(
                    kind="exclusion", label="but not", children=[base_part, subtract_part]
                )


def _usersets(root: ExpandNode) -> dict[str, ExpandNode]:
    found: dict[str, ExpandNode] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.kind == "userset":
            found[node.label] = node
        stack.extend(node.children)
    return found


def tree_contains(root: ExpandNode, subject: SubjectRef) -> bool:
    """Whether `subject` belongs to the expanded userset.

    References make the expansion a graph that may contain cycles, so membership is
    the least fixpoint over its usersets: start from "not a member" everywhere and
    re-evaluate until nothing changes.
    """
    usersets = _usersets(root)
    member: dict[str, bool] = dict.fromkeys(usersets, False)
    subject_label = str(subject)

    def evaluate(node: ExpandNode) -> bool:
        match node.kind:
            case "subject":
                if node.subject == subject_label:
                    return True
                stored = SubjectRef.parse(node.subject or "")
                return (
                    stored.is_wildcard and stored.type == subject.type and subject.relation is None
                )
            case "userset" | "ref":
                if subject.relation is not None and node.label == subject_label:
                    return True
                return member.get(node.label, False)
            case "intersection":
                return bool(node.children) and all(evaluate(c) for c in node.children)
            case "exclusion":
                base, subtract = node.children
                return evaluate(base) and not evaluate(subtract)
            case _:
                return any(evaluate(c) for c in node.children)

    changed = True
    while changed:
        changed = False
        for label, node in usersets.items():
            if member[label]:
                continue
            reflexive = subject.relation is not None and label == subject_label
            if reflexive or (node.children and evaluate(node.children[0])):
                member[label] = True
                changed = True
    return evaluate(root)


def collect_subjects(node: ExpandNode) -> set[SubjectRef]:
    """Every concrete subject and userset mentioned anywhere in the expansion."""
    found: set[SubjectRef] = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if n.kind == "subject" and n.subject:
            found.add(SubjectRef.parse(n.subject))
        elif n.kind in {"userset", "ref"} and n.object and n.relation:
            obj = ObjectRef.parse(n.object)
            found.add(SubjectRef(obj.type, obj.id, n.relation))
        stack.extend(n.children)
    return found
