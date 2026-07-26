"""Add platform synchronization scheduling and auditable runs.

Revision ID: 20260725_0003
Revises: 20260725_0002
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0003"
down_revision: str | None = "20260725_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "sync_interval_seconds",
                sa.BigInteger(),
                server_default="3600",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("last_sync_error_code", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("last_sync_error_message", sa.Text(), nullable=True))
        batch_op.create_index("ix_accounts_next_sync_at", ["next_sync_at"])

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("adapter_key", sa.String(120), nullable=False),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("lock_key", sa.String(255), nullable=True),
        sa.CheckConstraint(
            "target_type IN ('account', 'account_contents', 'content_item')",
            name="sync_run_target_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'success', 'error', 'skipped')",
            name="sync_run_status",
        ),
        sa.CheckConstraint("records_created >= 0", name="sync_run_created_nonnegative"),
        sa.CheckConstraint("records_updated >= 0", name="sync_run_updated_nonnegative"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lock_key"),
    )
    op.create_index("ix_sync_runs_workspace_id", "sync_runs", ["workspace_id"])
    op.create_index("ix_sync_runs_target_id", "sync_runs", ["target_id"])
    op.create_index("ix_sync_runs_adapter_key", "sync_runs", ["adapter_key"])
    op.create_index("ix_sync_runs_request_id", "sync_runs", ["request_id"])
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])
    op.create_index("ix_sync_runs_workspace_started", "sync_runs", ["workspace_id", "started_at"])
    op.create_index("ix_sync_runs_target_started", "sync_runs", ["target_type", "target_id", "started_at"])


def downgrade() -> None:
    op.drop_table("sync_runs")
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_index("ix_accounts_next_sync_at")
        batch_op.drop_column("last_sync_error_message")
        batch_op.drop_column("last_sync_error_code")
        batch_op.drop_column("sync_interval_seconds")
        batch_op.drop_column("next_sync_at")
