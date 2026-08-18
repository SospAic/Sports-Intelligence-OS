"""Add shared queue handling state and saved views."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260817_0005"
down_revision = "20260817_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_queue_states",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("assignee_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "item_kind IN ('task', 'notification')", name="inbox_queue_item_kind"
        ),
        sa.CheckConstraint(
            "state IN ('open', 'in_progress', 'completed')", name="inbox_queue_state"
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "item_kind", "item_id", name="uq_inbox_queue_states_item"
        ),
    )
    op.create_index("ix_inbox_queue_states_workspace_id", "inbox_queue_states", ["workspace_id"])
    op.create_index(
        "ix_inbox_queue_states_workspace_updated",
        "inbox_queue_states",
        ["workspace_id", "updated_at"],
    )
    op.create_index(
        "ix_inbox_queue_states_workspace_assignee",
        "inbox_queue_states",
        ["workspace_id", "assignee_id"],
    )

    op.create_table(
        "inbox_saved_views",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_inbox_saved_views_workspace_name"
        ),
    )
    op.create_index(
        "ix_inbox_saved_views_workspace_name", "inbox_saved_views", ["workspace_id", "name"]
    )


def downgrade() -> None:
    op.drop_index("ix_inbox_saved_views_workspace_name", table_name="inbox_saved_views")
    op.drop_table("inbox_saved_views")
    op.drop_index(
        "ix_inbox_queue_states_workspace_assignee", table_name="inbox_queue_states"
    )
    op.drop_index("ix_inbox_queue_states_workspace_updated", table_name="inbox_queue_states")
    op.drop_index("ix_inbox_queue_states_workspace_id", table_name="inbox_queue_states")
    op.drop_table("inbox_queue_states")
