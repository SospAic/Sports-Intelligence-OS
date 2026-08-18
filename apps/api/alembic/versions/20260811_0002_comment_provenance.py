"""Add comment provenance and author fields for hot-comment collection."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260811_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comments", sa.Column("author_url", sa.String(length=1000), nullable=True))
    op.add_column(
        "comments", sa.Column("author_avatar_url", sa.String(length=2000), nullable=True)
    )
    op.add_column(
        "comments", sa.Column("parent_comment_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "comments",
        sa.Column("is_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "comments",
        sa.Column("source_kind", sa.String(length=16), nullable=False, server_default="live"),
    )
    op.add_column(
        "comments",
        sa.Column("source_provider", sa.String(length=120), nullable=False, server_default="yt_dlp"),
    )
    op.add_column("comments", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column(
        "comments",
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("comments", "is_reply", server_default=None)
    op.alter_column("comments", "source_kind", server_default=None)
    op.alter_column("comments", "source_provider", server_default=None)
    op.alter_column("comments", "metadata", server_default=None)


def downgrade() -> None:
    op.drop_column("comments", "metadata")
    op.drop_column("comments", "source_url")
    op.drop_column("comments", "source_provider")
    op.drop_column("comments", "source_kind")
    op.drop_column("comments", "is_reply")
    op.drop_column("comments", "parent_comment_id")
    op.drop_column("comments", "author_avatar_url")
    op.drop_column("comments", "author_url")
