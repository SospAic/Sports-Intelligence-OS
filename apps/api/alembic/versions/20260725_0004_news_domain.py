"""Create news sources, articles, topic events, sync logs, and scoring configuration.

Revision ID: 20260725_0004
Revises: 20260725_0003
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0004"
down_revision: str | None = "20260725_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("reliability_score", sa.Numeric(6, 3), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider_key", sa.String(120), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("source_type IN ('rss', 'atom', 'json', 'manual')", name="news_source_type"),
        sa.CheckConstraint("reliability_score >= 0 AND reliability_score <= 100", name="news_source_reliability_range"),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="news_source_priority_range"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name"),
    )
    for name, columns in (
        ("ix_news_sources_workspace_id", ["workspace_id"]),
        ("ix_news_sources_source_type", ["source_type"]),
        ("ix_news_sources_category", ["category"]),
        ("ix_news_sources_language", ["language"]),
        ("ix_news_sources_country", ["country"]),
        ("ix_news_sources_enabled", ["enabled"]),
        ("ix_news_sources_provider_key", ["provider_key"]),
        ("ix_news_sources_next_sync_at", ["next_sync_at"]),
        ("ix_news_sources_workspace_enabled", ["workspace_id", "enabled"]),
    ):
        op.create_index(name, "news_sources", columns)

    op.create_table(
        "topic_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("normalized_title", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sport", sa.String(120), nullable=True),
        sa.Column("league", sa.String(120), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_update_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("article_count", sa.Integer(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("heat_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("reliability_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("controversy_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("visual_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("story_score", sa.Numeric(8, 4), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("is_bookmarked", sa.Boolean(), nullable=False),
        sa.Column("bookmarked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'developing', 'closed')", name="topic_event_status"),
        sa.CheckConstraint("heat_score >= 0 AND heat_score <= 100", name="event_heat_range"),
        sa.CheckConstraint("reliability_score >= 0 AND reliability_score <= 100", name="event_reliability_range"),
        sa.CheckConstraint("controversy_score >= 0 AND controversy_score <= 100", name="event_controversy_range"),
        sa.CheckConstraint("visual_score >= 0 AND visual_score <= 100", name="event_visual_range"),
        sa.CheckConstraint("story_score >= 0 AND story_score <= 100", name="event_story_range"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_topic_events_workspace_id", ["workspace_id"]),
        ("ix_topic_events_normalized_title", ["normalized_title"]),
        ("ix_topic_events_sport", ["sport"]),
        ("ix_topic_events_league", ["league"]),
        ("ix_topic_events_status", ["status"]),
        ("ix_topic_events_is_bookmarked", ["is_bookmarked"]),
        ("ix_topic_events_workspace_updated", ["workspace_id", "last_update_time"]),
        ("ix_topic_events_workspace_heat", ["workspace_id", "heat_score"]),
        ("ix_topic_events_workspace_sport", ["workspace_id", "sport"]),
    ):
        op.create_index(name, "topic_events", columns)

    op.create_table(
        "articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("sport", sa.String(120), nullable=True),
        sa.Column("league", sa.String(120), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("duplicate_group_id", sa.Uuid(), nullable=True),
        sa.Column("is_bookmarked", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_provider", sa.String(120), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("raw_payload_ref", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("source_kind IN ('live', 'imported')", name="news_article_source_kind"),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    for name, columns in (
        ("ix_articles_workspace_id", ["workspace_id"]),
        ("ix_articles_source_id", ["source_id"]),
        ("ix_articles_published_at", ["published_at"]),
        ("ix_articles_language", ["language"]),
        ("ix_articles_sport", ["sport"]),
        ("ix_articles_league", ["league"]),
        ("ix_articles_country", ["country"]),
        ("ix_articles_content_hash", ["content_hash"]),
        ("ix_articles_duplicate_group_id", ["duplicate_group_id"]),
        ("ix_articles_is_bookmarked", ["is_bookmarked"]),
        ("ix_articles_source_kind", ["source_kind"]),
        ("ix_articles_workspace_published", ["workspace_id", "published_at"]),
        ("ix_articles_workspace_fetched", ["workspace_id", "fetched_at"]),
        ("ix_articles_source_published", ["source_id", "published_at"]),
        ("ix_articles_workspace_sport", ["workspace_id", "sport"]),
        ("ix_articles_workspace_duplicate", ["workspace_id", "duplicate_group_id"]),
    ):
        op.create_index(name, "articles", columns)

    op.create_table(
        "event_articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("match_score", sa.Numeric(8, 6), nullable=False),
        sa.Column("linked_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["topic_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "article_id"),
    )
    op.create_index("ix_event_articles_event_id", "event_articles", ["event_id"])
    op.create_index("ix_event_articles_article_id", "event_articles", ["article_id"])
    op.create_index("ix_event_articles_article_event", "event_articles", ["article_id", "event_id"])

    op.create_table(
        "news_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(120), nullable=False),
        sa.Column("request_id", sa.String(120), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("lock_key", sa.String(255), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'success', 'error', 'skipped')", name="news_sync_run_status"),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lock_key"),
    )
    for name, columns in (
        ("ix_news_sync_runs_workspace_id", ["workspace_id"]),
        ("ix_news_sync_runs_source_id", ["source_id"]),
        ("ix_news_sync_runs_provider_key", ["provider_key"]),
        ("ix_news_sync_runs_request_id", ["request_id"]),
        ("ix_news_sync_runs_status", ["status"]),
        ("ix_news_sync_runs_source_started", ["source_id", "started_at"]),
        ("ix_news_sync_runs_workspace_started", ["workspace_id", "started_at"]),
    ):
        op.create_index(name, "news_sync_runs", columns)

    op.create_table(
        "news_scoring_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("source_weight", sa.Numeric(8, 4), nullable=False),
        sa.Column("freshness_weight", sa.Numeric(8, 4), nullable=False),
        sa.Column("source_count_weight", sa.Numeric(8, 4), nullable=False),
        sa.Column("article_count_weight", sa.Numeric(8, 4), nullable=False),
        sa.Column("user_interest_weight", sa.Numeric(8, 4), nullable=False),
        sa.Column("freshness_half_life_hours", sa.Numeric(8, 3), nullable=False),
        sa.Column("title_similarity_threshold", sa.Numeric(6, 5), nullable=False),
        sa.Column("event_similarity_threshold", sa.Numeric(6, 5), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("freshness_half_life_hours > 0", name="news_freshness_half_life"),
        sa.CheckConstraint("title_similarity_threshold >= 0 AND title_similarity_threshold <= 1", name="news_title_similarity_range"),
        sa.CheckConstraint("event_similarity_threshold >= 0 AND event_similarity_threshold <= 1", name="news_event_similarity_range"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "version"),
    )
    op.create_index("ix_news_scoring_configs_workspace_id", "news_scoring_configs", ["workspace_id"])
    op.create_index("ix_news_scoring_configs_is_active", "news_scoring_configs", ["is_active"])


def downgrade() -> None:
    op.drop_table("news_scoring_configs")
    op.drop_table("news_sync_runs")
    op.drop_table("event_articles")
    op.drop_table("articles")
    op.drop_table("topic_events")
    op.drop_table("news_sources")
