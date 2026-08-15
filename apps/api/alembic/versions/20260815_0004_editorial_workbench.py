"""Add editorial workbench members, bulk filters and saved views."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260815_0004"
down_revision = "20260815_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_saved_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("overdue", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unassigned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("priority_min", sa.Integer(), nullable=True),
        sa.Column("priority_max", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('draft', 'in_review', 'approved', 'rejected', 'archived')",
            name="editorial_saved_view_status",
        ),
        sa.CheckConstraint(
            "priority_min IS NULL OR (priority_min >= 0 AND priority_min <= 100)",
            name="editorial_saved_view_priority_min",
        ),
        sa.CheckConstraint(
            "priority_max IS NULL OR (priority_max >= 0 AND priority_max <= 100)",
            name="editorial_saved_view_priority_max",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_editorial_saved_views_workspace_name"
        ),
    )
    op.create_index(
        "ix_editorial_saved_views_workspace", "editorial_saved_views", ["workspace_id", "name"]
    )
    op.alter_column("editorial_saved_views", "overdue", server_default=None)
    op.alter_column("editorial_saved_views", "unassigned", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_editorial_saved_views_workspace", table_name="editorial_saved_views")
    op.drop_table("editorial_saved_views")
