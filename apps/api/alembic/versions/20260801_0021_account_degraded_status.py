"""Allow 'degraded' account sync status.

A sync run may finish with metrics partially extracted (e.g. the account
profile updated but per-content analytics unavailable). Previously the code
forced ``account.sync_status = 'success'`` in that case, which falsified the
monitoring state. We now persist the real ``degraded`` status so the UI can
show "部分同步（指标缺失）" instead of a misleading "监控中".

Revision ID: 20260801_0021
Revises: 20260801_0020
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0021"
down_revision: str | None = "20260801_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "sync_status IN ('never', 'queued', 'syncing', 'success', 'error', 'disabled')"
)
_NEW = (
    "sync_status IN ('never', 'queued', 'syncing', 'success', 'degraded', "
    "'error', 'disabled')"
)


def upgrade() -> None:
    op.drop_constraint("account_sync_status", "accounts", type_="check")
    op.create_check_constraint("account_sync_status", "accounts", _NEW)


def downgrade() -> None:
    op.drop_constraint("account_sync_status", "accounts", type_="check")
    op.create_check_constraint("account_sync_status", "accounts", _OLD)
