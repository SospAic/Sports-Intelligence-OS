"""Add ``media`` JSON column to ``content_items``.

Stores the relative reference map for locally-archived media (thumbnail /
video / subtitles / info json) produced by download-capable adapters during a
sync. ``NULL`` means no files were archived for that work.

Revision ID: 20260803_0004
Revises: 20260803_0003
Create Date: 2026-08-03 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_0004"
down_revision = "20260803_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("media", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_items", "media")
