"""Complete structured operation errors and expose news-source attempts.

The original error-detail migration added hints to generation runs but left
their code-level fields in the legacy JSON column.  This migration makes the
same structured fields queryable as the other operation records and preserves
the old JSON for backwards compatibility.  News sources also need a separate
last-attempt timestamp because ``last_synced_at`` means *last success*.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0005"
down_revision: str | None = "20260805_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generation_runs", sa.Column("error_code", sa.String(120), nullable=True))
    op.add_column("generation_runs", sa.Column("error_detail_safe", sa.Text(), nullable=True))
    op.add_column("news_sources", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        sa.text(
            "UPDATE generation_runs "
            "SET error_code = NULLIF(error->>'code', ''), "
            "error_detail_safe = NULLIF(COALESCE(error->>'detail', error->>'message'), '') "
            "WHERE error IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_column("news_sources", "last_attempt_at")
    op.drop_column("generation_runs", "error_detail_safe")
    op.drop_column("generation_runs", "error_code")
