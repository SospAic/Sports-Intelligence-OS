"""Add per-account scrape configuration to ``accounts``.

Two new columns support the configurable scrape behaviour requested for
account monitoring:

- ``max_contents_per_sync`` caps how many contents a single sync run will
  ingest for the account (``NULL`` = use the global default).
- ``adapter_config`` is a JSON bag of adapter-specific scrape parameters
  (e.g. yt-dlp options such as ``dateafter`` / ``datebefore`` / total item
  cap). It is merged into the ``AdapterCallContext.config`` each sync so
  adapters can honour operator-tunable settings without code changes.

The existing ``AccountRead`` schema already strips any ``adapter_config`` key
from ``metadata_json`` on read, so moving the value to a dedicated column
keeps credentials-free scrape settings explicit and auditable.

Revision ID: 20260802_0025
Revises: 20260801_0024
Create Date: 2026-08-02 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260802_0025"
down_revision = "20260801_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    # Backfill existing rows so the NOT NULL constraint is satisfied on
    # databases created before this migration.
    op.execute("UPDATE accounts SET adapter_config = '{}'::json WHERE adapter_config IS NULL")


def downgrade() -> None:
    op.drop_column("accounts", "adapter_config")
    op.drop_constraint("account_max_contents_per_sync_positive", "accounts", type_="check")
    op.drop_column("accounts", "max_contents_per_sync")
