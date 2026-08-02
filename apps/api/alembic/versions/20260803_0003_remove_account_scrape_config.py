"""Remove per-account scrape configuration from ``accounts``.

The ``max_contents_per_sync`` and ``adapter_config`` columns are no longer
used: the fetch policy moved to the workspace-scoped ``sync_settings`` table
(see ``20260803_0002_add_sync_settings``). Drop both columns and the
``max_contents_per_sync`` check constraint.

Revision ID: 20260803_0003
Revises: 20260803_0002
Create Date: 2026-08-03 00:03:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_0003"
down_revision = "20260803_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("accounts", "adapter_config")
    op.drop_constraint(
        "ck_accounts_account_max_contents_per_sync_positive", "accounts", type_="check"
    )
    op.drop_column("accounts", "max_contents_per_sync")


def downgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("max_contents_per_sync", sa.BigInteger(), nullable=True),
    )
    op.create_check_constraint(
        "account_max_contents_per_sync_positive",
        "accounts",
        "max_contents_per_sync IS NULL OR max_contents_per_sync >= 1",
    )
    op.add_column(
        "accounts",
        sa.Column(
            "adapter_config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.execute(
        "UPDATE accounts SET adapter_config = '{}'::json WHERE adapter_config IS NULL"
    )
