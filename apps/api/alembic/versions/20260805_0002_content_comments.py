"""Add comments table for hot-comment collection and ranking.

Stores best-effort platform comments per content item (yt-dlp extraction for
YouTube / TikTok / Douyin). Like/reply counts may be NULL when the source does
not expose them. The API ranks by likes + 3x replies and caps the hot-comments
widget at 20.

Revision ID: 20260805_0002
Revises: 20260805_0001
Create Date: 2026-08-05 01:10:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260805_0002"
down_revision = "20260805_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "content_item_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("platform_comment_id", sa.String(length=255), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("reply_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["content_item_id"], ["content_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_item_id", "platform_comment_id"),
    )
    op.create_index(
        "ix_comments_content_item_like",
        "comments",
        ["content_item_id", "like_count"],
    )


def downgrade() -> None:
    op.drop_index("ix_comments_content_item_like", table_name="comments")
    op.drop_table("comments")
