"""Add downloads table for on-demand video / subtitle fetching.

Created when an operator submits a URL on the download page; a Celery task
fetches it via yt-dlp and stores the resulting media (video / subtitles /
thumbnail / info-json) under MEDIA_ROOT/<workspace>/downloads/<id>/.

Revision ID: 20260805_0003
Revises: 20260805_0002
Create Date: 2026-08-05 01:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260805_0003"
down_revision = "20260805_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "downloads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("media", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_downloads_workspace_status", "downloads", ["workspace_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_downloads_workspace_status", table_name="downloads")
    op.drop_table("downloads")
