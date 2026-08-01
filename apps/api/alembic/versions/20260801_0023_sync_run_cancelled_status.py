"""Allow user-initiated cancellation of sync runs.

Adds the ``'cancelled'`` value to two CHECK constraints so a sync run (and its
account) can be moved into a terminal ``cancelled`` state when a user terminates
a queued/running sync. The cancel endpoint only records intent against the
persisted run and releases the account lock — it never asserts a successful
platform call, preserving the project's no-fake-success rule.

Revision ID: 20260801_0023
Revises: 20260801_0022
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0023"
down_revision: str | None = "20260801_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SYNC_RUN_STATUS_NEW = (
    "status IN ('queued', 'running', 'success', 'degraded', 'error', 'skipped', 'cancelled')"
)
_SYNC_RUN_STATUS_OLD = (
    "status IN ('queued', 'running', 'success', 'degraded', 'error', 'skipped')"
)
_ACCOUNT_SYNC_STATUS_NEW = (
    "sync_status IN ('never', 'queued', 'syncing', 'success', "
    "'degraded', 'error', 'disabled', 'cancelled')"
)
_ACCOUNT_SYNC_STATUS_OLD = (
    "sync_status IN ('never', 'queued', 'syncing', 'success', "
    "'degraded', 'error', 'disabled')"
)


def upgrade() -> None:
    op.drop_constraint("sync_run_status", "sync_runs", type_="check")
    op.create_check_constraint("sync_run_status", "sync_runs", _SYNC_RUN_STATUS_NEW)
    op.drop_constraint("account_sync_status", "accounts", type_="check")
    op.create_check_constraint(
        "account_sync_status", "accounts", _ACCOUNT_SYNC_STATUS_NEW
    )


def downgrade() -> None:
    op.drop_constraint("sync_run_status", "sync_runs", type_="check")
    op.create_check_constraint("sync_run_status", "sync_runs", _SYNC_RUN_STATUS_OLD)
    op.drop_constraint("account_sync_status", "accounts", type_="check")
    op.create_check_constraint(
        "account_sync_status", "accounts", _ACCOUNT_SYNC_STATUS_OLD
    )
