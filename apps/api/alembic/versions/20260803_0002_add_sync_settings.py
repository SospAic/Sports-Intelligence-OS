"""Create workspace-scoped sync settings table.

Holds the centralised yt-dlp / scrape tuning for a workspace. This replaces the
per-account ``accounts.adapter_config`` / ``accounts.max_contents_per_sync``
columns so every account in a workspace shares one fetch policy (works cap,
duplicate-skip behaviour and yt-dlp window parameters).

Revision ID: 20260803_0002
Revises: 20260803_0001
Create Date: 2026-08-03 00:02:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_0002"
down_revision = "20260803_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )
    op.create_index("ix_sync_settings_workspace_id", "sync_settings", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_settings_workspace_id", table_name="sync_settings")
    op.drop_table("sync_settings")
