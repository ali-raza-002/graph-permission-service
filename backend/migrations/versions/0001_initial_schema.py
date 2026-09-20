"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-04 14:53:26.396526
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_api_keys_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("prefix", name=op.f("uq_api_keys_prefix")),
    )
    op.create_index(op.f("ix_api_keys_store_id"), "api_keys", ["store_id"], unique=False)
    op.create_table(
        "authorization_models",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("dsl", sa.Text(), nullable=False),
        sa.Column("ast", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_authorization_models_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_authorization_models")),
        sa.UniqueConstraint(
            "store_id", "version", name=op.f("uq_authorization_models_store_id_version")
        ),
    )
    op.create_index(
        op.f("ix_authorization_models_store_id"), "authorization_models", ["store_id"], unique=False
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=False),
        sa.Column("model_id", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("object", sa.String(length=330), nullable=False),
        sa.Column("relation", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=400), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("cached", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("contextual_tuples", sa.Integer(), server_default="0", nullable=False),
        sa.Column("api_key_id", sa.String(length=40), nullable=True),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_decisions_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decisions")),
    )
    op.create_index(
        "ix_decisions_store_created", "decisions", ["store_id", "created_at"], unique=False
    )
    op.create_index("ix_decisions_store_id_desc", "decisions", ["store_id", "id"], unique=False)
    op.create_table(
        "relation_tuples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=False),
        sa.Column("object_type", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.String(length=256), nullable=False),
        sa.Column("relation", sa.String(length=64), nullable=False),
        sa.Column("subject_type", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("subject_relation", sa.String(length=64), server_default="", nullable=False),
        sa.Column("created_revision", sa.BigInteger(), nullable=False),
        sa.Column("deleted_revision", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_relation_tuples_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relation_tuples")),
    )
    op.create_index(
        "ix_relation_tuples_created",
        "relation_tuples",
        ["store_id", "created_revision"],
        unique=False,
    )
    op.create_index(
        "ix_relation_tuples_deleted",
        "relation_tuples",
        ["store_id", "deleted_revision"],
        unique=False,
        postgresql_where=sa.text("deleted_revision IS NOT NULL"),
    )
    op.create_index(
        "ix_relation_tuples_forward",
        "relation_tuples",
        ["store_id", "object_type", "object_id", "relation"],
        unique=False,
        postgresql_include=[
            "subject_type",
            "subject_id",
            "subject_relation",
            "created_revision",
            "deleted_revision",
        ],
    )
    op.create_index(
        "ix_relation_tuples_reverse",
        "relation_tuples",
        ["store_id", "subject_type", "subject_id", "subject_relation", "object_type", "relation"],
        unique=False,
        postgresql_include=["object_id", "created_revision", "deleted_revision"],
    )
    op.create_index(
        "uq_relation_tuples_live",
        "relation_tuples",
        [
            "store_id",
            "object_type",
            "object_id",
            "relation",
            "subject_type",
            "subject_id",
            "subject_relation",
        ],
        unique=True,
        postgresql_where=sa.text("deleted_revision IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_relation_tuples_live",
        table_name="relation_tuples",
        postgresql_where=sa.text("deleted_revision IS NULL"),
    )
    op.drop_index(
        "ix_relation_tuples_reverse",
        table_name="relation_tuples",
        postgresql_include=["object_id", "created_revision", "deleted_revision"],
    )
    op.drop_index(
        "ix_relation_tuples_forward",
        table_name="relation_tuples",
        postgresql_include=[
            "subject_type",
            "subject_id",
            "subject_relation",
            "created_revision",
            "deleted_revision",
        ],
    )
    op.drop_index(
        "ix_relation_tuples_deleted",
        table_name="relation_tuples",
        postgresql_where=sa.text("deleted_revision IS NOT NULL"),
    )
    op.drop_index("ix_relation_tuples_created", table_name="relation_tuples")
    op.drop_table("relation_tuples")
    op.drop_index("ix_decisions_store_id_desc", table_name="decisions")
    op.drop_index("ix_decisions_store_created", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index(op.f("ix_authorization_models_store_id"), table_name="authorization_models")
    op.drop_table("authorization_models")
    op.drop_index(op.f("ix_api_keys_store_id"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("stores")
