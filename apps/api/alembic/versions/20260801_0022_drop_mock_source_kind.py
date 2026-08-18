"""Drop the 'mock' source kind and its demo seed data.

The user removed all mock modules and demo seed data to validate the system
through real-data contracts only. This migration (1) deletes any rows that
were created with ``source_kind = 'mock'`` (including the legacy demo platform
and its orphaned derived metrics) and (2) tightens the ``source_kind`` CHECK
constraints on the monitoring and news tables so they no longer permit
'mock'. Real adapters only ever produce ``'live'`` data and imported data is
``'imported'``; 'mock' is no longer a valid or permitted value.

Revision ID: 20260801_0022
Revises: 20260801_0021
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0022"
down_revision: str | None = "20260801_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_CHECK = "source_kind IN ('live', 'imported')"

_SOURCE_KIND_TABLES = (
    ("accounts", "account_source_kind"),
    ("account_snapshots", "account_snapshot_source_kind"),
    ("content_items", "content_item_source_kind"),
    ("content_snapshots", "content_snapshot_source_kind"),
    ("articles", "news_article_source_kind"),
)


def upgrade() -> None:
    # 1. Remove mock data so the tightened constraints can be applied.
    op.execute(
        "DELETE FROM derived_metrics "
        "WHERE entity_id IN (SELECT id FROM content_items WHERE source_kind = 'mock')"
    )
    op.execute("DELETE FROM content_snapshots WHERE source_kind = 'mock'")
    op.execute("DELETE FROM account_snapshots WHERE source_kind = 'mock'")
    op.execute("DELETE FROM content_items WHERE source_kind = 'mock'")
    op.execute("DELETE FROM accounts WHERE source_kind = 'mock'")
    op.execute("DELETE FROM platforms WHERE key = 'demo_mock'")
    op.execute("DELETE FROM articles WHERE source_kind = 'mock'")

    # 2. Tighten the source_kind CHECK constraints to drop 'mock'.
    for table, constraint in _SOURCE_KIND_TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, _NEW_CHECK)


def downgrade() -> None:
    _OLD_CHECK = "source_kind IN ('live', 'imported', 'mock')"
    for table, constraint in _SOURCE_KIND_TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, _OLD_CHECK)
