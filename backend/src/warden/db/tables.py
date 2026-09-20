from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class StoreRow(Base):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    # Oldest revision that can still be read. History below it has been garbage-collected.
    gc_revision: Mapped[int] = mapped_column(BigInteger, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RevisionRow(Base):
    """Commit time of each store revision, used to turn a time-based retention window
    into a revision horizon."""

    __tablename__ = "store_revisions"

    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    committed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelRow(Base):
    __tablename__ = "authorization_models"
    __table_args__ = (UniqueConstraint("store_id", "version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(16))
    dsl: Mapped[str] = mapped_column(Text)
    ast: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TupleRow(Base):
    """A relationship tuple with MVCC-style visibility.

    A tuple is visible at revision R when created_revision <= R and it was not deleted
    at or before R. Rows are never updated except to stamp deleted_revision, so any
    revision can be read consistently without holding a transaction open.
    """

    __tablename__ = "relation_tuples"
    __table_args__ = (
        Index(
            "uq_relation_tuples_live",
            "store_id",
            "object_type",
            "object_id",
            "relation",
            "subject_type",
            "subject_id",
            "subject_relation",
            unique=True,
            postgresql_where=text("deleted_revision IS NULL"),
        ),
        Index(
            "ix_relation_tuples_forward",
            "store_id",
            "object_type",
            "object_id",
            "relation",
            postgresql_include=[
                "subject_type",
                "subject_id",
                "subject_relation",
                "created_revision",
                "deleted_revision",
            ],
        ),
        Index(
            "ix_relation_tuples_reverse",
            "store_id",
            "subject_type",
            "subject_id",
            "subject_relation",
            "object_type",
            "relation",
            postgresql_include=["object_id", "created_revision", "deleted_revision"],
        ),
        Index("ix_relation_tuples_created", "store_id", "created_revision"),
        Index(
            "ix_relation_tuples_deleted",
            "store_id",
            "deleted_revision",
            postgresql_where=text("deleted_revision IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    object_type: Mapped[str] = mapped_column(String(64))
    object_id: Mapped[str] = mapped_column(String(256))
    relation: Mapped[str] = mapped_column(String(64))
    subject_type: Mapped[str] = mapped_column(String(64))
    subject_id: Mapped[str] = mapped_column(String(256))
    # Empty string rather than NULL so the live-uniqueness index treats it as a value.
    subject_relation: Mapped[str] = mapped_column(String(64), server_default="")
    created_revision: Mapped[int] = mapped_column(BigInteger)
    deleted_revision: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiKeyRow(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    store_id: Mapped[str | None] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DecisionRow(Base):
    __tablename__ = "decisions"
    __table_args__ = (
        Index("ix_decisions_store_created", "store_id", "created_at"),
        Index("ix_decisions_store_id_desc", "store_id", "id"),
        Index("ix_decisions_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    model_id: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(24))
    object: Mapped[str] = mapped_column(String(330))
    relation: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(400))
    allowed: Mapped[bool | None] = mapped_column(Boolean)
    result_count: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float] = mapped_column(Float)
    cached: Mapped[bool] = mapped_column(Boolean, server_default="false")
    contextual_tuples: Mapped[int] = mapped_column(Integer, server_default="0")
    api_key_id: Mapped[str | None] = mapped_column(String(40))
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
