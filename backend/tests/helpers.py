from __future__ import annotations

from collections.abc import Iterable

from warden.core.refs import RelationTuple
from warden.engine.reader import MemoryTupleReader

WORKSPACE_MODEL = """
model
  schema 1.1

type user

type group
  relations
    define member: [user, group#member]

type folder
  relations
    define owner: [user]
    define parent: [folder]
    define editor: [user, group#member] or owner or editor from parent
    define viewer: [user, user:*, group#member] or editor or viewer from parent

type document
  relations
    define parent: [folder]
    define owner: [user]
    define blocked: [user]
    define editor: [user, group#member] or owner or editor from parent
    define viewer: ([user, group#member] or editor or viewer from parent) but not blocked
    define can_share: owner and editor
"""


def reader_of(tuples: Iterable[str]) -> MemoryTupleReader:
    return MemoryTupleReader(RelationTuple.parse(t) for t in tuples)
