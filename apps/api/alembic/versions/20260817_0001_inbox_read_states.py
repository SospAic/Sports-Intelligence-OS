"""Persist per-user read receipts for the operations inbox."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260817_0001"
down_revision = "20260816_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_read_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_kind", sa.String(length=32), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_kind IN ('task', 'notification')",
            name="inbox_read_state_item_kind",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            "item_kind",
            "item_id",
            name="uq_inbox_read_states_user_item",
        ),
    )
    op.create_index(
        "ix_inbox_read_states_workspace_id",
        "inbox_read_states",
        ["workspace_id"],
    )
    op.create_index("ix_inbox_read_states_user_id", "inbox_read_states", ["user_id"])
    op.create_index(
        "ix_inbox_read_states_workspace_user_read",
        "inbox_read_states",
        ["workspace_id", "user_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbox_read_states_workspace_user_read",
        table_name="inbox_read_states",
    )
    op.drop_index("ix_inbox_read_states_user_id", table_name="inbox_read_states")
    op.drop_index("ix_inbox_read_states_workspace_id", table_name="inbox_read_states")
    op.drop_table("inbox_read_states")
