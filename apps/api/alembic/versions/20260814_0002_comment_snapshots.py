"""Store append-only ranked comment observations."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260814_0002"
down_revision = "20260814_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=False),
        sa.Column("comment_id", sa.Uuid(), nullable=False),
        sa.Column("platform_comment_id", sa.String(length=255), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("reply_count", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comment_id", "captured_at"),
    )
    op.create_index(
        "ix_comment_snapshots_workspace_id", "comment_snapshots", ["workspace_id"]
    )
    op.create_index(
        "ix_comment_snapshots_content_item_id", "comment_snapshots", ["content_item_id"]
    )
    op.create_index("ix_comment_snapshots_comment_id", "comment_snapshots", ["comment_id"])
    op.create_index(
        "ix_comment_snapshots_content_captured",
        "comment_snapshots",
        ["content_item_id", "captured_at"],
    )
    op.create_index(
        "ix_comment_snapshots_platform_id",
        "comment_snapshots",
        ["content_item_id", "platform_comment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_comment_snapshots_platform_id", table_name="comment_snapshots")
    op.drop_index("ix_comment_snapshots_content_captured", table_name="comment_snapshots")
    op.drop_index("ix_comment_snapshots_comment_id", table_name="comment_snapshots")
    op.drop_index("ix_comment_snapshots_content_item_id", table_name="comment_snapshots")
    op.drop_index("ix_comment_snapshots_workspace_id", table_name="comment_snapshots")
    op.drop_table("comment_snapshots")
