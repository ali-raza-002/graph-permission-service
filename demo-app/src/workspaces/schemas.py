from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SUBJECT = re.compile(
    r"^(user:[a-z0-9_-]+|user:\*|team:[a-z0-9_-]+#member|org:[a-z0-9_-]+#member)$"
)


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    handle: str
    name: str
    title: str
    email: str

    @property
    def subject(self) -> str:
        return f"user:{self.handle}"


class Team(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    org_id: str


class Folder(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    org_id: str
    parent_id: str | None
    name: str
    description: str


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    folder_id: str
    title: str
    created_by: str
    updated_at: datetime


class Document(DocumentSummary):
    body: str
    created_at: datetime


class Permissions(BaseModel):
    can_edit: bool
    can_share: bool
    can_delete: bool


class Authorization(BaseModel):
    decision_id: str
    revision: int
    duration_ms: float


class FolderDetail(BaseModel):
    folder: Folder
    documents: list[DocumentSummary]
    can_create: bool
    authorization: Authorization


class DocumentDetail(BaseModel):
    document: Document
    permissions: Permissions
    authorization: Authorization


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=50_000)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=50_000)


Role = Literal["viewer", "editor", "blocked"]


class Share(BaseModel):
    subject: str = Field(description="user:<handle>, user:*, team:<id>#member or org:<id>#member")
    role: Role

    @field_validator("subject")
    @classmethod
    def _valid_subject(cls, value: str) -> str:
        if not _SUBJECT.match(value):
            raise ValueError("subject must be a user, team or org membership")
        return value


class ShareView(BaseModel):
    """A share as stored in Warden. Tuples can also be written from the console, so the
    subject is not held to the input format of Share."""

    subject: str
    role: Role


class Access(BaseModel):
    owner: list[str]
    shares: list[ShareView]
    effective_viewers: list[str]
    can_share: bool
    can_manage: bool = Field(description="May block people and remove shares.")
