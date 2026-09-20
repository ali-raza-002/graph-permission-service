from __future__ import annotations

import re
from dataclasses import dataclass

NAME_PATTERN = r"[A-Za-z_][A-Za-z0-9_-]{0,63}"
ID_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_\-.@|+=/:]{0,255}"
WILDCARD = "*"

_NAME_RE = re.compile(rf"^{NAME_PATTERN}$")
_OBJECT_RE = re.compile(rf"^(?P<type>{NAME_PATTERN}):(?P<id>{ID_PATTERN})$")
_SUBJECT_RE = re.compile(
    rf"^(?P<type>{NAME_PATTERN}):(?P<id>{ID_PATTERN}|\*)(?:#(?P<relation>{NAME_PATTERN}))?$"
)


class RefParseError(ValueError):
    pass


def is_valid_name(value: str) -> bool:
    return _NAME_RE.match(value) is not None


@dataclass(frozen=True, slots=True)
class ObjectRef:
    type: str
    id: str

    @classmethod
    def parse(cls, raw: str) -> ObjectRef:
        match = _OBJECT_RE.match(raw)
        if match is None:
            raise RefParseError(f"'{raw}' is not a valid object, expected 'type:id'")
        return cls(match["type"], match["id"])

    def __str__(self) -> str:
        return f"{self.type}:{self.id}"


@dataclass(frozen=True, slots=True)
class SubjectRef:
    type: str
    id: str
    relation: str | None = None

    @classmethod
    def parse(cls, raw: str) -> SubjectRef:
        match = _SUBJECT_RE.match(raw)
        if match is None:
            raise RefParseError(
                f"'{raw}' is not a valid subject, "
                "expected 'type:id', 'type:*' or 'type:id#relation'"
            )
        if match["id"] == WILDCARD and match["relation"]:
            raise RefParseError(f"'{raw}' is invalid: a wildcard subject cannot carry a relation")
        return cls(match["type"], match["id"], match["relation"])

    @property
    def is_wildcard(self) -> bool:
        return self.id == WILDCARD

    @property
    def is_userset(self) -> bool:
        return self.relation is not None

    def as_object(self) -> ObjectRef:
        return ObjectRef(self.type, self.id)

    def __str__(self) -> str:
        base = f"{self.type}:{self.id}"
        return f"{base}#{self.relation}" if self.relation else base


@dataclass(frozen=True, slots=True)
class RelationTuple:
    object: ObjectRef
    relation: str
    subject: SubjectRef

    @classmethod
    def of(cls, obj: str, relation: str, subject: str) -> RelationTuple:
        if not is_valid_name(relation):
            raise RefParseError(f"'{relation}' is not a valid relation name")
        return cls(ObjectRef.parse(obj), relation, SubjectRef.parse(subject))

    @classmethod
    def parse(cls, raw: str) -> RelationTuple:
        """Parse the canonical 'type:id#relation@subject' notation.

        Object ids may contain '@' but never '#', and relation names contain neither, so
        splitting on the first '#' and then the first '@' is unambiguous.
        """
        obj, sep, rest = raw.partition("#")
        relation, sep2, subject = rest.partition("@")
        if not sep or not sep2:
            raise RefParseError(
                f"'{raw}' is not a valid tuple, expected 'type:id#relation@subject'"
            )
        return cls.of(obj, relation, subject)

    def __str__(self) -> str:
        return f"{self.object}#{self.relation}@{self.subject}"
