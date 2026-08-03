"""Add ``sync_settings_override`` JSON column to ``accounts``.

Per-account override of the workspace-wide sync settings (currently the
``download`` sub-object). ``NULL`` means the account inherits the workspace
policy; when present it is deep-merged on top of the workspace config by the
sync executor.

Revision ID: 20260803_0005
Revises: 20260803_0004
Create Date: 2026-08-03 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_0005"
down_revision = "20260803_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("sync_settings_override", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "sync_settings_override")
