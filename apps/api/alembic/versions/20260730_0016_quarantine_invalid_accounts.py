"""Quarantine known error-page account records without deleting user data.

Revision ID: 20260730_0016
Revises: 20260730_0015
Create Date: 2026-07-30 11:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260730_0016"
down_revision = "20260730_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE accounts AS account
            SET metadata = COALESCE(account.metadata, '{}'::json)::jsonb ||
                    jsonb_build_object(
                        'quarantined_by', '20260730_0016',
                        'quarantine_reason', 'legacy_error_page_identity',
                        'previous_is_active', account.is_active,
                        'previous_sync_status', account.sync_status,
                        'previous_source_kind', account.source_kind,
                        'previous_source_provider', account.source_provider
                    ),
                is_active = false,
                sync_status = 'disabled',
                source_kind = 'imported',
                source_provider = 'legacy_invalid'
            WHERE lower(trim(account.display_name)) IN (
                    '404 not found', '403 forbidden', 'page not found'
                )
              AND NOT EXISTS (
                    SELECT 1 FROM content_items AS content
                    WHERE content.account_id = account.id
                )
              AND (
                    account.metadata->>'method' = 'browser_scrape'
                    OR account.source_provider ILIKE '%browser%'
                )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE news_sources AS source
            SET config = COALESCE(source.config, '{}'::json)::jsonb ||
                    jsonb_build_object(
                        'quarantined', true,
                        'quarantined_by', '20260730_0016',
                        'quarantine_reason', 'legacy_crud_test_record'
                    )
            WHERE source.enabled = false
              AND (
                    source.name IN ('Manual Test Source', 'Updated Source Name')
                    OR source.url LIKE 'https://example.com/feed-%'
                )
              AND NOT EXISTS (
                    SELECT 1 FROM articles AS article
                    WHERE article.source_id = source.id
                )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE news_sources
            SET config = COALESCE(config, '{}'::json)::jsonb ||
                    jsonb_build_object(
                        'renamed_by', '20260730_0016',
                        'previous_name', name
                    ),
                name = replace(name, '（示例，默认停用）', '')
            WHERE enabled = true
              AND name LIKE '%（示例，默认停用）'
              AND NOT EXISTS (
                    SELECT 1 FROM news_sources AS existing
                    WHERE existing.workspace_id = news_sources.workspace_id
                      AND existing.name = replace(
                            news_sources.name, '（示例，默认停用）', ''
                        )
                )
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE news_sources
            SET config = (config::jsonb - 'quarantined'
                - 'quarantined_by' - 'quarantine_reason')
            WHERE config->>'quarantined_by' = '20260730_0016'
              AND config->>'quarantine_reason' = 'legacy_crud_test_record'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE news_sources
            SET name = config->>'previous_name',
                config = (config::jsonb - 'renamed_by' - 'previous_name')
            WHERE config->>'renamed_by' = '20260730_0016'
              AND config->>'previous_name' IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET is_active = COALESCE((metadata->>'previous_is_active')::boolean, false),
                sync_status = COALESCE(metadata->>'previous_sync_status', 'error'),
                source_kind = COALESCE(metadata->>'previous_source_kind', 'imported'),
                source_provider = COALESCE(
                    metadata->>'previous_source_provider', 'manual'
                ),
                metadata = (metadata::jsonb - 'quarantined_by'
                    - 'quarantine_reason' - 'previous_is_active'
                    - 'previous_sync_status' - 'previous_source_kind'
                    - 'previous_source_provider')
            WHERE metadata->>'quarantined_by' = '20260730_0016'
            """
        )
    )
