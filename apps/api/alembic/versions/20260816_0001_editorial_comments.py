"""Add auditable collaboration comments to editorial items."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260816_0001"
down_revision = "20260815_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("editorial_item_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(btrim(body)) > 0", name="editorial_comment_body_not_blank"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["editorial_item_id"], ["editorial_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_editorial_comments_workspace_id",
        "editorial_comments",
        ["workspace_id"],
    )
    op.create_index(
        "ix_editorial_comments_editorial_item_id",
        "editorial_comments",
        ["editorial_item_id"],
    )
    op.create_index(
        "ix_editorial_comments_author_id",
        "editorial_comments",
        ["author_id"],
    )
    op.create_index(
        "ix_editorial_comments_resolved_by",
        "editorial_comments",
        ["resolved_by"],
    )
    op.create_index(
        "ix_editorial_comments_workspace_item_created",
        "editorial_comments",
        ["workspace_id", "editorial_item_id", "created_at"],
    )
    op.create_index(
        "ix_editorial_comments_item_resolved",
        "editorial_comments",
        ["editorial_item_id", "resolved_at"],
    )
    op.alter_column("editorial_comments", "created_at", server_default=None)
    op.alter_column("editorial_comments", "updated_at", server_default=None)


def downgrade() -> None:
    for index_name in (
        "ix_editorial_comments_item_resolved",
        "ix_editorial_comments_workspace_item_created",
        "ix_editorial_comments_resolved_by",
        "ix_editorial_comments_author_id",
        "ix_editorial_comments_editorial_item_id",
        "ix_editorial_comments_workspace_id",
    ):
        op.drop_index(index_name, table_name="editorial_comments")
    op.drop_table("editorial_comments")
