"""Add sync_run_events append-only tracklog table.

Every SyncRun now emits a structured, per-step log (stage transitions, page
listings, per-content upserts, analytics fetches and caught exceptions) so
operators can replay exactly what a sync did and where it degraded, instead of
only seeing a terminal success/error summary. The table is append-only and
cascades with its parent sync_runs row.

Revision ID: 20260804_0002
Revises: 20260804_0001
Create Date: 2026-08-04 19:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260804_0002"
down_revision = "20260804_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_run_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"], ["sync_runs.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "event_type IN ('stage', 'page', 'item', 'analytics', "
            "'external_call', 'warning', 'error', 'info', 'summary')",
            name="sync_run_event_type",
        ),
        sa.CheckConstraint(
            "level IN ('info', 'warn', 'error')", name="sync_run_event_level"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sync_run_events_run_sequence",
        "sync_run_events",
        ["sync_run_id", "sequence"],
    )
    op.create_index(
        "ix_sync_run_events_run_created",
        "sync_run_events",
        ["sync_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_run_events_run_created", table_name="sync_run_events")
    op.drop_index("ix_sync_run_events_run_sequence", table_name="sync_run_events")
    op.drop_table("sync_run_events")
