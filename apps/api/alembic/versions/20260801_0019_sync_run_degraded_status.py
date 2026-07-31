"""Add 'degraded' to sync_runs status constraint.

Allows sync runs to be marked as degraded when the profile was updated
successfully but all key metrics (follower_count, video_count, total_view_count)
came back as NULL, indicating an extraction failure.

Revision ID: 20260801_0019
Revises: 20260731_0018
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0019"
down_revision: str | None = "20260731_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("sync_run_status", "sync_runs", type_="check")
    op.create_check_constraint(
        "sync_run_status",
        "sync_runs",
        "status IN ('queued', 'running', 'success', 'degraded', 'error', 'skipped')",
    )


def downgrade() -> None:
    # Revert any degraded runs to success before tightening the constraint.
    op.execute("UPDATE sync_runs SET status = 'success' WHERE status = 'degraded'")
    op.drop_constraint("sync_run_status", "sync_runs", type_="check")
    op.create_check_constraint(
        "sync_run_status",
        "sync_runs",
        "status IN ('queued', 'running', 'success', 'error', 'skipped')",
    )
