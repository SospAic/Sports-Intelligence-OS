"""Add isolated ASR / subtitle translation jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260813_0003"
down_revision = "20260811_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subtitle_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("asr_backend", sa.String(length=64), nullable=False),
        sa.Column("source_language", sa.String(length=32), nullable=True),
        sa.Column(
            "target_languages",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "progress",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "result",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subtitle_jobs_workspace_status", "subtitle_jobs", ["workspace_id", "status"])
    op.create_index("ix_subtitle_jobs_content_created", "subtitle_jobs", ["content_item_id", "created_at"])
    op.create_index("ix_subtitle_jobs_workspace_id", "subtitle_jobs", ["workspace_id"])
    op.create_index("ix_subtitle_jobs_content_item_id", "subtitle_jobs", ["content_item_id"])
    op.create_index("ix_subtitle_jobs_status", "subtitle_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_subtitle_jobs_status", table_name="subtitle_jobs")
    op.drop_index("ix_subtitle_jobs_content_item_id", table_name="subtitle_jobs")
    op.drop_index("ix_subtitle_jobs_workspace_id", table_name="subtitle_jobs")
    op.drop_index("ix_subtitle_jobs_content_created", table_name="subtitle_jobs")
    op.drop_index("ix_subtitle_jobs_workspace_status", table_name="subtitle_jobs")
    op.drop_table("subtitle_jobs")
