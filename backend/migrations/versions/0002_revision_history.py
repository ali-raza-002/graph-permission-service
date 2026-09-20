"""revision history and garbage-collection horizon

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 20:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stores",
        sa.Column("gc_revision", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_table(
        "store_revisions",
        sa.Column("store_id", sa.String(length=40), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "committed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_store_revisions_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("store_id", "revision", name=op.f("pk_store_revisions")),
    )
    op.create_index("ix_decisions_created_at", "decisions", ["created_at"], unique=False)
    op.execute(
        "INSERT INTO store_revisions (store_id, revision, committed_at) "
        "SELECT id, revision, updated_at FROM stores WHERE revision > 0"
    )


def downgrade() -> None:
    op.drop_index("ix_decisions_created_at", table_name="decisions")
    op.drop_table("store_revisions")
    op.drop_column("stores", "gc_revision")
