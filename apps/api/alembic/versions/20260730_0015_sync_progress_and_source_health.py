"""Add synchronization progress and news source failure health.

Revision ID: 20260730_0015
Revises: 20260729_0014
Create Date: 2026-07-30 10:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260730_0015"
down_revision = "20260729_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.add_column(
            sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("progress_stage", sa.String(length=64), nullable=False, server_default="queued")
        )
        batch_op.add_column(sa.Column("progress_message", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("items_processed", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("items_total", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "sync_run_progress_range", "progress_percent >= 0 AND progress_percent <= 100"
        )
        batch_op.create_check_constraint(
            "sync_run_items_processed_nonnegative", "items_processed >= 0"
        )

    op.execute(
        sa.text(
            """
            UPDATE sync_runs
            SET progress_percent = CASE WHEN status = 'success' THEN 100 ELSE 0 END,
                progress_stage = CASE
                    WHEN status = 'success' THEN 'completed'
                    WHEN status = 'error' THEN 'failed'
                    WHEN status = 'running' THEN 'validating'
                    ELSE 'queued'
                END,
                progress_message = CASE
                    WHEN status = 'success' THEN '历史同步已完成'
                    WHEN status = 'error' THEN '历史同步失败'
                    ELSE NULL
                END
            """
        )
    )

    with op.batch_alter_table("news_sources") as batch_op:
        batch_op.add_column(
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "news_source_failures_nonnegative", "consecutive_failures >= 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("news_sources") as batch_op:
        batch_op.drop_constraint("news_source_failures_nonnegative", type_="check")
        batch_op.drop_column("consecutive_failures")

    with op.batch_alter_table("sync_runs") as batch_op:
        batch_op.drop_constraint("sync_run_items_processed_nonnegative", type_="check")
        batch_op.drop_constraint("sync_run_progress_range", type_="check")
        batch_op.drop_column("items_total")
        batch_op.drop_column("items_processed")
        batch_op.drop_column("progress_message")
        batch_op.drop_column("progress_stage")
        batch_op.drop_column("progress_percent")
