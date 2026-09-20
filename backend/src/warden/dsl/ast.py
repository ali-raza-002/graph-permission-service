"""Typed AST for authorization models.

Nodes are immutable so a compiled model can be shared freely between concurrent
checks. Source positions are kept for diagnostics but excluded from serialization and
equality, so two models that differ only in layout compare and hash the same.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourcePos(BaseModel):
    model_config = ConfigDict(frozen=True)

    line: int
    column: int


class _Node(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pos: SourcePos | None = Field(default=None, exclude=True, repr=False)

    def _identity(self) -> tuple[object, ...]:
        return tuple(v for k, v in self.__dict__.items() if k != "pos")

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return NotImplemented
        assert isinstance(other, _Node)
        return self._identity() == other._identity()

    def __hash__(self) -> int:
        return hash((type(self), self._identity()))


class TypeRestriction(_Node):
    type: str
    relation: str | None = None
    wildcard: bool = False

    def __str__(self) -> str:
        if self.wildcard:
            return f"{self.type}:*"
        if self.relation:
            return f"{self.type}#{self.relation}"
        return self.type


class DirectNode(_Node):
    kind: Literal["direct"] = "direct"
    types: tuple[TypeRestriction, ...]


class ComputedNode(_Node):
    kind: Literal["computed"] = "computed"
    relation: str


class TupleToUsersetNode(_Node):
    kind: Literal["tuple_to_userset"] = "tuple_to_userset"
    tupleset: str
    computed: str


class UnionNode(_Node):
    kind: Literal["union"] = "union"
    children: tuple[Rewrite, ...]


class IntersectionNode(_Node):
    kind: Literal["intersection"] = "intersection"
    children: tuple[Rewrite, ...]


class ExclusionNode(_Node):
    kind: Literal["exclusion"] = "exclusion"
    base: Rewrite
    subtract: Rewrite


Rewrite = Annotated[
    DirectNode | ComputedNode | TupleToUsersetNode | UnionNode | IntersectionNode | ExclusionNode,
    Field(discriminator="kind"),
]


class RelationDef(_Node):
    name: str
    rewrite: Rewrite


class TypeDef(_Node):
    name: str
    relations: tuple[RelationDef, ...] = ()


class AuthorizationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1.1"
    types: tuple[TypeDef, ...] = ()


for _model in (
    UnionNode,
    IntersectionNode,
    ExclusionNode,
    RelationDef,
    TypeDef,
    AuthorizationModel,
):
    _model.model_rebuild()
