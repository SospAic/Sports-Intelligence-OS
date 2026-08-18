"""Add tags array column to content_items for the works-data filter.

Creator-assigned / platform-extracted topic tags (e.g. yt-dlp "tags") are now
persisted on each content row as a native Postgres text array so the works-data
page can offer a fast multi-select "has any of these tags" (&& overlap) filter.

Revision ID: 20260805_0001
Revises: 20260804_0003
Create Date: 2026-08-05 00:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260805_0001"
down_revision = "20260804_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    # backfill any NULLs (e.g. rows written before the server_default landed)
    op.execute("UPDATE content_items SET tags = '{}'::text[] WHERE tags IS NULL")
    op.create_index(
        "ix_content_items_tags",
        "content_items",
        ["tags"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_tags", table_name="content_items")
    op.drop_column("content_items", "tags")
