"""Add user_view_preferences table for per-user workspace-scoped view settings.

Stores filters, sort order, layout and column visibility preferences so they
persist across devices instead of relying solely on browser localStorage.

Revision ID: 20260731_0018
Revises: 20260731_0017
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260731_0018"
down_revision: str | None = "20260731_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_view_preferences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("view_key", sa.String(64), nullable=False),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_view_preferences"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_user_view_preferences_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_view_preferences_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id", "user_id", "view_key", name="uq_user_view_preferences_workspace_id"
        ),
    )
    op.create_index(
        "ix_user_view_preferences_workspace_user",
        "user_view_preferences",
        ["workspace_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_view_preferences_workspace_user", table_name="user_view_preferences")
    op.drop_table("user_view_preferences")
