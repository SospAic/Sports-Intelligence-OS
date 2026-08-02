"""Add code-level and business-level error detail to ``sync_runs``.

Operators need more than a single ``error_message`` string to act on failed
synchronisations. Two new nullable text columns capture structured failure
information:

- ``error_detail`` — the code-level details (exception class, origin, adapter
  key, trace id) so developers can debug without grepping logs.
- ``error_hint`` — the business-level explanation and remediation steps mapped
  from ``error_code``, shown to operators so they know *what to do* next.

Both are nullable and back-filled to ``NULL`` for existing rows.

Revision ID: 20260802_0030
Revises: 20260802_0025
Create Date: 2026-08-02 22:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260802_0030"
down_revision = "20260802_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column("error_detail", sa.Text(), nullable=True),
    )
    op.add_column(
        "sync_runs",
        sa.Column("error_hint", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_runs", "error_hint")
    op.drop_column("sync_runs", "error_detail")
