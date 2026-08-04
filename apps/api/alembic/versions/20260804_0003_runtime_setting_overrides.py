"""Add runtime_setting_overrides table for restart-free Settings overrides.

A small global key/value table that lets a few server-level Settings (today only
``sync_task_max_retries``) be adjusted at runtime through the UI and take effect
without an application restart. The worker reads this table at sync-task time
instead of the frozen environment-derived ``Settings`` singleton.

Revision ID: 20260804_0003
Revises: 20260804_0002
Create Date: 2026-08-04 20:50:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260804_0003"
down_revision = "20260804_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_setting_overrides",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column(
            "value_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_runtime_setting_overrides_updated_by",
        "runtime_setting_overrides",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_setting_overrides_updated_by",
        table_name="runtime_setting_overrides",
    )
    op.drop_table("runtime_setting_overrides")
