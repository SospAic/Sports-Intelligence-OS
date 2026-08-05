"""Align model-owned indexes with the historical PostgreSQL schema.

The application models had accumulated a few useful column indexes that were
not represented in migrations, while some older migrations already provided
composite indexes with different names.  This migration adds only the missing
single-column indexes and leaves the existing composite indexes intact.

Revision ID: 20260805_0006
Revises: 20260805_0005
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260805_0006"
down_revision: str | None = "20260805_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'audit_entries'::regclass
                  AND conname = 'ck_audit_entries_status'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'audit_entries'::regclass
                  AND conname = 'ck_audit_entries_ck_audit_entries_status'
            ) THEN
                ALTER TABLE audit_entries
                RENAME CONSTRAINT ck_audit_entries_status
                TO ck_audit_entries_ck_audit_entries_status;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'cross_platform_links'::regclass
                  AND conname = 'ck_cross_platform_links_cross_platform_link_confidence_range'
            ) THEN
                ALTER TABLE cross_platform_links
                ADD CONSTRAINT ck_cross_platform_links_cross_platform_link_confidence_range
                CHECK (confidence >= 0 AND confidence <= 1);
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'cross_platform_links'::regclass
                  AND conname = 'ck_cross_platform_links_cross_platform_link_status'
            ) THEN
                ALTER TABLE cross_platform_links
                ADD CONSTRAINT ck_cross_platform_links_cross_platform_link_status
                CHECK (status IN ('suggested', 'confirmed', 'rejected'));
            END IF;
        END $$;
        """
    )
    op.create_index("ix_comments_content_item_id", "comments", ["content_item_id"])
    op.create_index("ix_comments_workspace_id", "comments", ["workspace_id"])
    op.create_index("ix_derivative_topics_platform", "derivative_topics", ["platform"])
    op.create_index("ix_derivative_topics_status", "derivative_topics", ["status"])
    op.create_index("ix_downloads_status", "downloads", ["status"])
    op.create_index("ix_downloads_workspace_id", "downloads", ["workspace_id"])
    op.create_index("ix_search_analyses_search_query_id", "search_analyses", ["search_query_id"])
    op.create_index("ix_search_analyses_workspace_id", "search_analyses", ["workspace_id"])
    op.create_index("ix_search_queries_workspace_id", "search_queries", ["workspace_id"])
    op.create_index("ix_sync_run_events_workspace_id", "sync_run_events", ["workspace_id"])


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'cross_platform_links'::regclass
                  AND conname = 'ck_cross_platform_links_cross_platform_link_status'
            ) THEN
                ALTER TABLE cross_platform_links
                DROP CONSTRAINT ck_cross_platform_links_cross_platform_link_status;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'cross_platform_links'::regclass
                  AND conname = 'ck_cross_platform_links_cross_platform_link_confidence_range'
            ) THEN
                ALTER TABLE cross_platform_links
                DROP CONSTRAINT ck_cross_platform_links_cross_platform_link_confidence_range;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'audit_entries'::regclass
                  AND conname = 'ck_audit_entries_ck_audit_entries_status'
            ) THEN
                ALTER TABLE audit_entries
                RENAME CONSTRAINT ck_audit_entries_ck_audit_entries_status
                TO ck_audit_entries_status;
            END IF;
        END $$;
        """
    )
    op.drop_index("ix_sync_run_events_workspace_id", table_name="sync_run_events")
    op.drop_index("ix_search_queries_workspace_id", table_name="search_queries")
    op.drop_index("ix_search_analyses_workspace_id", table_name="search_analyses")
    op.drop_index("ix_search_analyses_search_query_id", table_name="search_analyses")
    op.drop_index("ix_downloads_workspace_id", table_name="downloads")
    op.drop_index("ix_downloads_status", table_name="downloads")
    op.drop_index("ix_derivative_topics_status", table_name="derivative_topics")
    op.drop_index("ix_derivative_topics_platform", table_name="derivative_topics")
    op.drop_index("ix_comments_workspace_id", table_name="comments")
    op.drop_index("ix_comments_content_item_id", table_name="comments")
