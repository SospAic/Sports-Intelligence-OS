"""Add the auditable editorial review queue."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0003"
down_revision = "20260815_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("generation_run_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')",
            name="editorial_item_status",
        ),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="editorial_item_priority"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation_run_id", name="uq_editorial_items_generation_run"),
    )
    for index_name, columns in (
        ("ix_editorial_items_workspace_id", ["workspace_id"]),
        ("ix_editorial_items_generation_run_id", ["generation_run_id"]),
        ("ix_editorial_items_created_by", ["created_by"]),
        ("ix_editorial_items_assignee_id", ["assignee_id"]),
        ("ix_editorial_items_status", ["status"]),
        ("ix_editorial_items_reviewed_by", ["reviewed_by"]),
        (
            "ix_editorial_items_workspace_status_priority",
            ["workspace_id", "status", "priority", "updated_at"],
        ),
        (
            "ix_editorial_items_workspace_assignee_status",
            ["workspace_id", "assignee_id", "status"],
        ),
        ("ix_editorial_items_workspace_due_at", ["workspace_id", "due_at"]),
    ):
        op.create_index(index_name, "editorial_items", columns)
    op.alter_column("editorial_items", "status", server_default=None)
    op.alter_column("editorial_items", "priority", server_default=None)
    op.alter_column("editorial_items", "content_snapshot", server_default=None)
    op.alter_column("editorial_items", "source_snapshot", server_default=None)


def downgrade() -> None:
    for index_name in (
        "ix_editorial_items_workspace_due_at",
        "ix_editorial_items_workspace_assignee_status",
        "ix_editorial_items_workspace_status_priority",
        "ix_editorial_items_reviewed_by",
        "ix_editorial_items_status",
        "ix_editorial_items_assignee_id",
        "ix_editorial_items_created_by",
        "ix_editorial_items_generation_run_id",
        "ix_editorial_items_workspace_id",
    ):
        op.drop_index(index_name, table_name="editorial_items")
    op.drop_table("editorial_items")
