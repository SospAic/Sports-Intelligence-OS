"""Create platform monitoring accounts, content, snapshots, and metrics.

Revision ID: 20260725_0002
Revises: 20260725_0001
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260725_0002"
down_revision: str | None = "20260725_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platforms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("adapter_key", sa.String(length=120), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_platforms_adapter_key", "platforms", ["adapter_key"])
    op.create_index("ix_platforms_category", "platforms", ["category"])
    op.create_index("ix_platforms_enabled", "platforms", ["enabled"])

    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("profile_url", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_status", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("source_kind IN ('live', 'imported', 'mock')", name="account_source_kind"),
        sa.CheckConstraint("sync_status IN ('never', 'queued', 'syncing', 'success', 'error', 'disabled')", name="account_sync_status"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "platform_id", "external_id"),
    )
    op.create_index("ix_accounts_is_active", "accounts", ["is_active"])
    op.create_index("ix_accounts_platform_id", "accounts", ["platform_id"])
    op.create_index("ix_accounts_source_kind", "accounts", ["source_kind"])
    op.create_index("ix_accounts_sync_status", "accounts", ["sync_status"])
    op.create_index("ix_accounts_username", "accounts", ["username"])
    op.create_index("ix_accounts_workspace_id", "accounts", ["workspace_id"])
    op.create_index("ix_accounts_workspace_last_synced", "accounts", ["workspace_id", "last_synced_at"])
    op.create_index("ix_accounts_workspace_platform_active", "accounts", ["workspace_id", "platform_id", "is_active"])

    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("follower_count", sa.BigInteger(), nullable=True),
        sa.Column("following_count", sa.BigInteger(), nullable=True),
        sa.Column("total_like_count", sa.BigInteger(), nullable=True),
        sa.Column("total_view_count", sa.BigInteger(), nullable=True),
        sa.Column("video_count", sa.BigInteger(), nullable=True),
        sa.Column("engagement_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("follower_count IS NULL OR follower_count >= 0", name="account_snapshot_follower_nonnegative"),
        sa.CheckConstraint("following_count IS NULL OR following_count >= 0", name="account_snapshot_following_nonnegative"),
        sa.CheckConstraint("total_like_count IS NULL OR total_like_count >= 0", name="account_snapshot_likes_nonnegative"),
        sa.CheckConstraint("total_view_count IS NULL OR total_view_count >= 0", name="account_snapshot_views_nonnegative"),
        sa.CheckConstraint("video_count IS NULL OR video_count >= 0", name="account_snapshot_videos_nonnegative"),
        sa.CheckConstraint("engagement_rate IS NULL OR (engagement_rate >= 0 AND engagement_rate <= 1)", name="account_snapshot_engagement_range"),
        sa.CheckConstraint("source_kind IN ('live', 'imported', 'mock')", name="account_snapshot_source_kind"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "captured_at"),
    )
    op.create_index("ix_account_snapshots_account_id", "account_snapshots", ["account_id"])
    op.create_index("ix_account_snapshots_captured_at", "account_snapshots", ["captured_at"])
    op.create_index("ix_account_snapshots_source_kind", "account_snapshots", ["source_kind"])
    op.create_index("ix_account_snapshots_account_captured", "account_snapshots", ["account_id", "captured_at"])

    op.create_table(
        "content_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("platform_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Numeric(14, 3), nullable=True),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("raw_payload_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="content_item_duration_nonnegative"),
        sa.CheckConstraint("source_kind IN ('live', 'imported', 'mock')", name="content_item_source_kind"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "platform_id", "external_id"),
    )
    op.create_index("ix_content_items_account_id", "content_items", ["account_id"])
    op.create_index("ix_content_items_content_type", "content_items", ["content_type"])
    op.create_index("ix_content_items_last_seen_at", "content_items", ["last_seen_at"])
    op.create_index("ix_content_items_platform_id", "content_items", ["platform_id"])
    op.create_index("ix_content_items_published_at", "content_items", ["published_at"])
    op.create_index("ix_content_items_source_kind", "content_items", ["source_kind"])
    op.create_index("ix_content_items_status", "content_items", ["status"])
    op.create_index("ix_content_items_workspace_id", "content_items", ["workspace_id"])
    op.create_index("ix_content_items_account_published", "content_items", ["account_id", "published_at"])
    op.create_index("ix_content_items_platform_published", "content_items", ["platform_id", "published_at"])
    op.create_index("ix_content_items_workspace_status", "content_items", ["workspace_id", "status"])

    op.create_table(
        "content_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content_item_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.BigInteger(), nullable=True),
        sa.Column("share_count", sa.BigInteger(), nullable=True),
        sa.Column("favorite_count", sa.BigInteger(), nullable=True),
        sa.Column("follower_gain", sa.BigInteger(), nullable=True),
        sa.Column("average_watch_time", sa.Numeric(14, 3), nullable=True),
        sa.Column("completion_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("search_traffic_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("recommendation_traffic_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("profile_traffic_rate", sa.Numeric(12, 8), nullable=True),
        sa.Column("revenue", sa.Numeric(20, 6), nullable=True),
        sa.Column("rpm", sa.Numeric(20, 6), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("source_provider", sa.String(length=120), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_ref", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("view_count IS NULL OR view_count >= 0", name="content_snapshot_views_nonnegative"),
        sa.CheckConstraint("like_count IS NULL OR like_count >= 0", name="content_snapshot_likes_nonnegative"),
        sa.CheckConstraint("comment_count IS NULL OR comment_count >= 0", name="content_snapshot_comments_nonnegative"),
        sa.CheckConstraint("share_count IS NULL OR share_count >= 0", name="content_snapshot_shares_nonnegative"),
        sa.CheckConstraint("favorite_count IS NULL OR favorite_count >= 0", name="content_snapshot_favorites_nonnegative"),
        sa.CheckConstraint("follower_gain IS NULL OR follower_gain >= 0", name="content_snapshot_followers_nonnegative"),
        sa.CheckConstraint("average_watch_time IS NULL OR average_watch_time >= 0", name="content_snapshot_watch_nonnegative"),
        sa.CheckConstraint("completion_rate IS NULL OR (completion_rate >= 0 AND completion_rate <= 1)", name="content_snapshot_completion_range"),
        sa.CheckConstraint("search_traffic_rate IS NULL OR (search_traffic_rate >= 0 AND search_traffic_rate <= 1)", name="content_snapshot_search_rate_range"),
        sa.CheckConstraint("recommendation_traffic_rate IS NULL OR (recommendation_traffic_rate >= 0 AND recommendation_traffic_rate <= 1)", name="content_snapshot_recommendation_rate_range"),
        sa.CheckConstraint("profile_traffic_rate IS NULL OR (profile_traffic_rate >= 0 AND profile_traffic_rate <= 1)", name="content_snapshot_profile_rate_range"),
        sa.CheckConstraint("source_kind IN ('live', 'imported', 'mock')", name="content_snapshot_source_kind"),
        sa.ForeignKeyConstraint(["content_item_id"], ["content_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_item_id", "captured_at"),
    )
    op.create_index("ix_content_snapshots_captured_at", "content_snapshots", ["captured_at"])
    op.create_index("ix_content_snapshots_content_item_id", "content_snapshots", ["content_item_id"])
    op.create_index("ix_content_snapshots_source_kind", "content_snapshots", ["source_kind"])
    op.create_index("ix_content_snapshots_content_captured", "content_snapshots", ["content_item_id", "captured_at"])
    op.create_index("ix_content_snapshots_captured_views", "content_snapshots", ["captured_at", "view_count"])

    op.create_table(
        "derived_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("window", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint("entity_type IN ('account', 'content_item')", name="derived_metric_entity_type"),
        sa.CheckConstraint("metric_key IN ('view_growth_1h', 'view_growth_6h', 'view_growth_24h', 'follower_growth_24h', 'engagement_rate', 'share_rate', 'favorite_rate', 'view_velocity', 'view_acceleration', 'median_views_30d', 'account_baseline_ratio', 'viral_score')", name="derived_metric_key"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "entity_type", "entity_id", "metric_key", "window", "calculated_at"),
    )
    op.create_index("ix_derived_metrics_calculated_at", "derived_metrics", ["calculated_at"])
    op.create_index("ix_derived_metrics_entity_id", "derived_metrics", ["entity_id"])
    op.create_index("ix_derived_metrics_metric_key", "derived_metrics", ["metric_key"])
    op.create_index("ix_derived_metrics_workspace_id", "derived_metrics", ["workspace_id"])
    op.create_index("ix_derived_metrics_entity_metric_calculated", "derived_metrics", ["entity_type", "entity_id", "metric_key", "calculated_at"])
    op.create_index("ix_derived_metrics_workspace_key_value", "derived_metrics", ["workspace_id", "metric_key", "value"])


def downgrade() -> None:
    op.drop_table("derived_metrics")
    op.drop_table("content_snapshots")
    op.drop_table("content_items")
    op.drop_table("account_snapshots")
    op.drop_table("accounts")
    op.drop_table("platforms")
