from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import UnexpectedCharacters, UnexpectedEOF, UnexpectedInput, UnexpectedToken
from lark.lexer import PatternStr
from lark.tree import Meta

from warden.dsl.ast import (
    AuthorizationModel,
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    RelationDef,
    Rewrite,
    SourcePos,
    TupleToUsersetNode,
    TypeDef,
    TypeRestriction,
    UnionNode,
)
from warden.dsl.issues import DslIssue, ModelCompileError

_FRIENDLY_TERMINALS = {
    "NAME": "a name",
    "SCHEMA_VERSION": "a schema version such as 1.1",
    "$END": "end of input",
}


@cache
def _lark() -> Lark:
    grammar = files("warden.dsl").joinpath("grammar.lark").read_text(encoding="utf-8")
    return Lark(grammar, parser="lalr", propagate_positions=True, maybe_placeholders=False)


def _pos_of_token(token: Token) -> SourcePos:
    return SourcePos(line=token.line or 1, column=token.column or 1)


def _pos_of_meta(meta: Meta) -> SourcePos | None:
    if getattr(meta, "empty", True):
        return None
    return SourcePos(line=meta.line, column=meta.column)


class _AstBuilder(Transformer[Token, AuthorizationModel]):
    def start(self, children: list[Any]) -> AuthorizationModel:
        schema = "1.1"
        types: list[TypeDef] = []
        for child in children:
            if isinstance(child, TypeDef):
                types.append(child)
            else:
                schema = str(child)
        return AuthorizationModel(schema_version=schema, types=tuple(types))

    def header(self, children: list[Token]) -> str:
        return str(children[0])

    def type_def(self, children: list[Any]) -> TypeDef:
        name: Token = children[0]
        relations: tuple[RelationDef, ...] = children[1] if len(children) > 1 else ()
        return TypeDef(name=str(name), relations=relations, pos=_pos_of_token(name))

    def relations(self, children: list[RelationDef]) -> tuple[RelationDef, ...]:
        return tuple(children)

    def relation_def(self, children: list[Any]) -> RelationDef:
        name: Token = children[0]
        rewrite: Rewrite = children[1]
        return RelationDef(name=str(name), rewrite=rewrite, pos=_pos_of_token(name))

    @v_args(meta=True)
    def union(self, meta: Meta, children: list[Rewrite]) -> UnionNode:
        flat: list[Rewrite] = []
        for child in children:
            flat.extend(child.children if isinstance(child, UnionNode) else (child,))
        return UnionNode(children=tuple(flat), pos=_pos_of_meta(meta))

    @v_args(meta=True)
    def intersection(self, meta: Meta, children: list[Rewrite]) -> IntersectionNode:
        flat: list[Rewrite] = []
        for child in children:
            flat.extend(child.children if isinstance(child, IntersectionNode) else (child,))
        return IntersectionNode(children=tuple(flat), pos=_pos_of_meta(meta))

    @v_args(meta=True)
    def exclusion(self, meta: Meta, children: list[Rewrite]) -> ExclusionNode:
        pos = _pos_of_meta(meta)
        node = ExclusionNode(base=children[0], subtract=children[1], pos=pos)
        for subtract in children[2:]:
            node = ExclusionNode(base=node, subtract=subtract, pos=pos)
        return node

    @v_args(meta=True)
    def direct(self, meta: Meta, children: list[TypeRestriction]) -> DirectNode:
        return DirectNode(types=tuple(children), pos=_pos_of_meta(meta))

    def plain_type(self, children: list[Token]) -> TypeRestriction:
        return TypeRestriction(type=str(children[0]), pos=_pos_of_token(children[0]))

    def wildcard_type(self, children: list[Token]) -> TypeRestriction:
        return TypeRestriction(type=str(children[0]), wildcard=True, pos=_pos_of_token(children[0]))

    def userset_type(self, children: list[Token]) -> TypeRestriction:
        return TypeRestriction(
            type=str(children[0]), relation=str(children[1]), pos=_pos_of_token(children[0])
        )

    def computed(self, children: list[Token]) -> ComputedNode:
        return ComputedNode(relation=str(children[0]), pos=_pos_of_token(children[0]))

    def tuple_to_userset(self, children: list[Token]) -> TupleToUsersetNode:
        computed, tupleset = children
        return TupleToUsersetNode(
            computed=str(computed), tupleset=str(tupleset), pos=_pos_of_token(computed)
        )


def _describe_terminal(name: str) -> str:
    if name in _FRIENDLY_TERMINALS:
        return _FRIENDLY_TERMINALS[name]
    try:
        pattern = _lark().get_terminal(name).pattern
    except KeyError:
        return name.lower()
    if isinstance(pattern, PatternStr):
        return f"'{pattern.value}'"
    return name.lower()


def _expected_list(expected: set[str]) -> str:
    names = sorted({_describe_terminal(name) for name in expected})
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" or {names[-1]}"


def _syntax_issue(exc: UnexpectedInput) -> DslIssue:
    line = max(getattr(exc, "line", 1) or 1, 1)
    column = max(getattr(exc, "column", 1) or 1, 1)
    length = 1
    if isinstance(exc, UnexpectedToken):
        token = exc.token
        if token.type == "$END":
            message = f"unexpected end of input, expected {_expected_list(exc.expected)}"
        else:
            length = len(str(token)) or 1
            message = f"unexpected '{token}', expected {_expected_list(exc.expected)}"
    elif isinstance(exc, UnexpectedCharacters):
        message = f"unexpected character '{exc.char}'"
    elif isinstance(exc, UnexpectedEOF):
        message = f"unexpected end of input, expected {_expected_list(set(exc.expected))}"
    else:
        message = str(exc)
    return DslIssue(
        code="syntax_error",
        message=message,
        line=line,
        column=column,
        end_line=line,
        end_column=column + length,
    )


def parse_model(source: str) -> AuthorizationModel:
    """Parse DSL source into an AST without semantic validation."""
    try:
        tree = _lark().parse(source)
    except UnexpectedInput as exc:
        raise ModelCompileError([_syntax_issue(exc)]) from exc
    result = _AstBuilder().transform(tree)
    assert isinstance(result, AuthorizationModel)
    return result
