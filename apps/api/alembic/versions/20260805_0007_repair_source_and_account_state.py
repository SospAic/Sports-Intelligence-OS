"""Quarantine known dead feeds and preserve operator account names.

The local database contains rows created by earlier seed versions.  Updating
the seed alone does not repair those rows, so this migration makes the repair
deterministic and keeps the original source rows for audit/history.

Revision ID: 20260805_0007
Revises: 20260805_0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260805_0007"
down_revision: str | None = "20260805_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RETIRED_FEEDS = (
    "https://apnews.com/index.rss",
    "https://www.goal.com/en/feeds/news",
    "https://hnrss.org/sports",
    "https://hnrss.org/search?q=sports",
    "https://www.cbssports.com/mlb/rss/headlines/",
    "https://www.cbssports.com/rss/headlines/",
    "https://www.cbssports.com/nfl/rss/headlines/",
    "https://www.cbssports.com/nba/rss/headlines/",
    "https://www.cbssports.com/nhl/rss/headlines/",
    "https://www.espn.com/espn/rss/news",
    "https://www.espn.com/espn/rss/nfl/news",
    "https://www.espn.com/espn/rss/nba/news",
    "https://www.reddit.com/r/nba/.rss",
    "https://www.reddit.com/r/soccer/.rss",
    "https://www.reddit.com/r/sports/.rss",
    "https://feeds.npr.org/104092227/feed.json",
)


def upgrade() -> None:
    # Keep failed rows for audit, but prevent the scheduler from retrying a
    # known dead/rate-limited endpoint on every cycle.
    op.execute(
        sa.text(
            """
            UPDATE news_sources
            SET enabled = FALSE,
                next_sync_at = NULL,
                last_error_code = 'source_quarantined',
                last_error_message = '已自动停用：连续同步失败或来源协议已变更，请改用权威替代源'
            WHERE url IN :urls
            """
        ).bindparams(sa.bindparam("urls", expanding=True, value=list(_RETIRED_FEEDS)))
    )

    # Enable the two authoritative replacement feeds when their seed rows
    # already exist.  The regular seed path creates them for fresh workspaces.
    op.execute(
        sa.text(
            """
            UPDATE news_sources
            SET enabled = TRUE,
                next_sync_at = NOW(),
                last_error_code = NULL,
                last_error_message = NULL,
                consecutive_failures = 0
            WHERE url IN ('http://feeds.bbci.co.uk/sport/rss.xml',
                          'https://www.theguardian.com/sport/rss')
            """
        )
    )

    # A manually entered display name must survive a later adapter refresh.
    # Existing rows predate the explicit marker; preserving their current
    # operator-visible name is the least surprising migration behaviour.
    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET metadata = (
                COALESCE(metadata::jsonb, '{}'::jsonb)
                || '{"display_name_source":"manual"}'::jsonb
            )::json
            WHERE COALESCE(metadata::jsonb ->> 'display_name_source', '') = ''
            """
        )
    )


def downgrade() -> None:
    # Do not resurrect unreliable feeds or remove the account protection on
    # downgrade; both changes are data-safety repairs.
    pass
