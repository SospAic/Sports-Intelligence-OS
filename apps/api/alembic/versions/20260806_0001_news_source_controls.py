"""Add browser acquisition and cancellable news source syncs."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260806_0001"
down_revision: str | None = "20260805_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("news_source_type", "news_sources", type_="check")
    op.create_check_constraint(
        "news_source_type",
        "news_sources",
        "source_type IN ('rss', 'atom', 'json', 'web', 'manual')",
    )
    op.drop_constraint("news_sync_run_status", "news_sync_runs", type_="check")
    op.create_check_constraint(
        "news_sync_run_status",
        "news_sync_runs",
        "status IN ('queued', 'running', 'success', 'error', 'skipped', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("news_sync_run_status", "news_sync_runs", type_="check")
    op.create_check_constraint(
        "news_sync_run_status",
        "news_sync_runs",
        "status IN ('queued', 'running', 'success', 'error', 'skipped')",
    )
    op.drop_constraint("news_source_type", "news_sources", type_="check")
    op.create_check_constraint(
        "news_source_type",
        "news_sources",
        "source_type IN ('rss', 'atom', 'json', 'manual')",
    )
