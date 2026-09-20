from __future__ import annotations

import pytest

from tests.helpers import WORKSPACE_MODEL
from warden.dsl import ModelCompileError, compile_model, format_model, parse_model, validate_model
from warden.dsl.ast import (
    ComputedNode,
    DirectNode,
    ExclusionNode,
    IntersectionNode,
    TupleToUsersetNode,
    UnionNode,
)


def _issues(source: str) -> list[tuple[str, int, int]]:
    with pytest.raises(ModelCompileError) as exc_info:
        compile_model(source)
    return [(i.code, i.line, i.column) for i in exc_info.value.issues]


def test_parses_every_rewrite_kind() -> None:
    model = compile_model(WORKSPACE_MODEL)
    document = next(t for t in model.types if t.name == "document")
    rewrites = {r.name: r.rewrite for r in document.relations}

    assert isinstance(rewrites["owner"], DirectNode)
    editor = rewrites["editor"]
    assert isinstance(editor, UnionNode)
    assert [type(c) for c in editor.children] == [DirectNode, ComputedNode, TupleToUsersetNode]
    ttu = editor.children[2]
    assert isinstance(ttu, TupleToUsersetNode)
    assert (ttu.computed, ttu.tupleset) == ("editor", "parent")

    viewer = rewrites["viewer"]
    assert isinstance(viewer, ExclusionNode)
    assert isinstance(viewer.base, UnionNode)
    assert viewer.subtract == ComputedNode(relation="blocked")
    assert isinstance(rewrites["can_share"], IntersectionNode)


def test_operator_precedence_binds_but_not_tightest() -> None:
    model = parse_model(
        "type user\ntype doc\n  relations\n"
        "    define a: [user]\n    define b: [user]\n    define c: [user]\n"
        "    define x: a or b and c but not a\n"
    )
    rewrite = model.types[1].relations[3].rewrite
    assert isinstance(rewrite, UnionNode)
    intersection = rewrite.children[1]
    assert isinstance(intersection, IntersectionNode)
    assert isinstance(intersection.children[1], ExclusionNode)


def test_wildcard_and_userset_restrictions() -> None:
    model = compile_model(WORKSPACE_MODEL)
    folder = next(t for t in model.types if t.name == "folder")
    viewer = next(r for r in folder.relations if r.name == "viewer").rewrite
    assert isinstance(viewer, UnionNode)
    direct = viewer.children[0]
    assert isinstance(direct, DirectNode)
    assert [str(t) for t in direct.types] == ["user", "user:*", "group#member"]


def test_format_round_trips() -> None:
    model = compile_model(WORKSPACE_MODEL)
    assert parse_model(format_model(model)).model_dump() == model.model_dump()


def test_format_adds_parentheses_only_when_needed() -> None:
    model = compile_model(WORKSPACE_MODEL)
    text = format_model(model)
    assert (
        "define viewer: ([user, group#member] or editor or viewer from parent) but not blocked"
        in text
    )
    assert "define can_share: owner and editor" in text


def test_comments_and_trailing_commas_are_accepted() -> None:
    compile_model("// people\ntype user // humans\ntype doc\n  relations\n    define v: [user,]\n")


def test_syntax_error_reports_line_and_column() -> None:
    source = "type user\ntype doc\n  relations\n    define viewer: [user] or\n"
    [(code, line, column)] = _issues(source)
    assert code == "syntax_error"
    assert line == 5 or (line == 4 and column > 20)


def test_syntax_error_message_lists_expected_tokens() -> None:
    with pytest.raises(ModelCompileError) as exc_info:
        compile_model("type doc\n  relations\n    define viewer [user]\n")
    issue = exc_info.value.issues[0]
    assert (issue.line, issue.column) == (3, 19)
    assert "':'" in issue.message


def test_unexpected_character() -> None:
    [(code, line, column)] = _issues("type user\ntype doc\n  relations\n    define v: [user] & x\n")
    assert (code, line, column) == ("syntax_error", 4, 22)


def test_unknown_type_and_relation_are_reported_with_positions() -> None:
    issues = _issues(
        "type user\n"
        "type doc\n"
        "  relations\n"
        "    define viewer: [usr]\n"
        "    define editor: [user] or ownr\n"
        "    define reader: [user, user#nope]\n"
    )
    assert ("unknown_type", 4, 21) in issues
    assert ("unknown_relation", 5, 30) in issues
    assert ("unknown_relation", 6, 27) in issues


def test_duplicate_definitions() -> None:
    issues = _issues(
        "type user\ntype user\ntype doc\n  relations\n    define a: [user]\n    define a: [user]\n"
    )
    assert ("duplicate_type", 2, 6) in issues
    assert ("duplicate_relation", 6, 12) in issues


def test_tupleset_must_be_direct_plain_types() -> None:
    issues = _issues(
        "type user\n"
        "type folder\n  relations\n    define viewer: [user]\n"
        "type doc\n  relations\n"
        "    define parent: [folder] or owner\n"
        "    define owner: [user]\n"
        "    define viewer: viewer from parent\n"
    )
    assert [c for c, *_ in issues] == ["invalid_tupleset"]


def test_tuple_to_userset_target_must_exist_on_parent() -> None:
    issues = _issues(
        "type user\n"
        "type folder\n  relations\n    define owner: [user]\n"
        "type doc\n  relations\n"
        "    define parent: [folder]\n    define viewer: viewer from parent\n"
    )
    assert issues == [("unknown_relation", 8, 20)]


def test_relations_without_entrypoint_are_rejected() -> None:
    issues = _issues(
        "type user\ntype doc\n  relations\n"
        "    define a: b\n    define b: a or c\n    define c: a and d\n    define d: [user]\n"
    )
    assert sorted(c for c, *_ in issues) == ["no_entrypoint"] * 3


def test_recursive_relation_with_entrypoint_is_valid() -> None:
    compile_model(
        "type user\ntype folder\n  relations\n"
        "    define parent: [folder]\n    define viewer: [user] or viewer from parent\n"
    )


def test_unsupported_schema_version() -> None:
    model = parse_model("model\n  schema 2.0\ntype user\n")
    assert [i.code for i in validate_model(model)] == ["unsupported_schema"]


def test_empty_source_is_an_empty_model() -> None:
    assert compile_model("").types == ()


def test_exclusion_chains_are_left_associative() -> None:
    model = compile_model(
        "type user\ntype doc\n  relations\n    define a: [user]\n    define b: [user]\n"
        "    define c: [user]\n    define d: a but not b but not c\n"
    )
    doc = next(t for t in model.types if t.name == "doc")
    d = next(r for r in doc.relations if r.name == "d").rewrite
    assert isinstance(d, ExclusionNode)
    assert isinstance(d.base, ExclusionNode)
    assert (d.base.base, d.base.subtract, d.subtract) == (
        ComputedNode(relation="a", pos=d.base.base.pos),
        ComputedNode(relation="b", pos=d.base.subtract.pos),
        ComputedNode(relation="c", pos=d.subtract.pos),
    )
    formatted = format_model(model)
    assert "define d: a but not b but not c" in formatted
    assert format_model(compile_model(formatted)) == formatted


def test_right_nested_exclusion_keeps_its_parentheses() -> None:
    source = (
        "type user\ntype doc\n  relations\n    define a: [user]\n    define b: [user]\n"
        "    define c: [user]\n    define d: a but not (b but not c)\n"
    )
    assert "define d: a but not (b but not c)" in format_model(compile_model(source))


def test_unused_types_are_warnings_not_errors() -> None:
    source = "type user\ntype ghost\ntype doc\n  relations\n    define viewer: [user]\n"
    issues = validate_model(parse_model(source))
    assert [(i.code, i.severity, i.line) for i in issues] == [("unused_type", "warning", 2)]
    compile_model(source)
