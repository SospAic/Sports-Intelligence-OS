from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.workspace import Workspace


SOURCE_KINDS = ("live", "imported", "mock")
DERIVED_METRIC_KEYS = (
    "view_growth_1h",
    "view_growth_6h",
    "view_growth_24h",
    "follower_growth_24h",
    "engagement_rate",
    "share_rate",
    "favorite_rate",
    "view_velocity",
    "view_acceleration",
    "median_views_30d",
    "account_baseline_ratio",
    "viral_score",
)


class Platform(TimestampMixin, Base):
    __tablename__ = "platforms"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    adapter_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    accounts: Mapped[list[Account]] = relationship(back_populates="platform")
    contents: Mapped[list[ContentItem]] = relationship(back_populates="platform")


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform_id", "external_id"),
        CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name="account_source_kind",
        ),
        CheckConstraint(
            "sync_status IN ('never', 'queued', 'syncing', 'success', 'error', 'disabled')",
            name="account_sync_status",
        ),
        Index("ix_accounts_workspace_platform_active", "workspace_id", "platform_id", "is_active"),
        Index("ix_accounts_workspace_last_synced", "workspace_id", "last_synced_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_id: Mapped[UUID] = mapped_column(
        ForeignKey("platforms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    sync_interval_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False, default=3600)
    sync_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="never", index=True
    )
    last_sync_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_sync_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="imported", index=True
    )
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False, default="manual")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    workspace: Mapped[Workspace] = relationship()
    platform: Mapped[Platform] = relationship(back_populates="accounts")
    snapshots: Mapped[list[AccountSnapshot]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    contents: Mapped[list[ContentItem]] = relationship(back_populates="account")


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "captured_at"),
        CheckConstraint(
            "follower_count IS NULL OR follower_count >= 0",
            name="account_snapshot_follower_nonnegative",
        ),
        CheckConstraint(
            "following_count IS NULL OR following_count >= 0",
            name="account_snapshot_following_nonnegative",
        ),
        CheckConstraint(
            "total_like_count IS NULL OR total_like_count >= 0",
            name="account_snapshot_likes_nonnegative",
        ),
        CheckConstraint(
            "total_view_count IS NULL OR total_view_count >= 0",
            name="account_snapshot_views_nonnegative",
        ),
        CheckConstraint(
            "video_count IS NULL OR video_count >= 0",
            name="account_snapshot_videos_nonnegative",
        ),
        CheckConstraint(
            "engagement_rate IS NULL OR (engagement_rate >= 0 AND engagement_rate <= 1)",
            name="account_snapshot_engagement_range",
        ),
        CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name="account_snapshot_source_kind",
        ),
        Index("ix_account_snapshots_account_captured", "account_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    follower_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    following_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_like_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    video_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    engagement_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped[Account] = relationship(back_populates="snapshots")


class ContentItem(TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform_id", "external_id"),
        CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name="content_item_source_kind",
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="content_item_duration_nonnegative",
        ),
        Index("ix_content_items_platform_published", "platform_id", "published_at"),
        Index("ix_content_items_account_published", "account_id", "published_at"),
        Index("ix_content_items_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_id: Mapped[UUID] = mapped_column(
        ForeignKey("platforms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="published", index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    platform: Mapped[Platform] = relationship(back_populates="contents")
    account: Mapped[Account] = relationship(back_populates="contents")
    snapshots: Mapped[list[ContentSnapshot]] = relationship(
        back_populates="content_item", cascade="all, delete-orphan"
    )


class ContentSnapshot(Base):
    __tablename__ = "content_snapshots"
    __table_args__ = (
        UniqueConstraint("content_item_id", "captured_at"),
        CheckConstraint(
            "view_count IS NULL OR view_count >= 0",
            name="content_snapshot_views_nonnegative",
        ),
        CheckConstraint(
            "like_count IS NULL OR like_count >= 0",
            name="content_snapshot_likes_nonnegative",
        ),
        CheckConstraint(
            "comment_count IS NULL OR comment_count >= 0",
            name="content_snapshot_comments_nonnegative",
        ),
        CheckConstraint(
            "share_count IS NULL OR share_count >= 0",
            name="content_snapshot_shares_nonnegative",
        ),
        CheckConstraint(
            "favorite_count IS NULL OR favorite_count >= 0",
            name="content_snapshot_favorites_nonnegative",
        ),
        CheckConstraint(
            "follower_gain IS NULL OR follower_gain >= 0",
            name="content_snapshot_followers_nonnegative",
        ),
        CheckConstraint(
            "average_watch_time IS NULL OR average_watch_time >= 0",
            name="content_snapshot_watch_nonnegative",
        ),
        CheckConstraint(
            "completion_rate IS NULL OR (completion_rate >= 0 AND completion_rate <= 1)",
            name="content_snapshot_completion_range",
        ),
        CheckConstraint(
            "search_traffic_rate IS NULL OR "
            "(search_traffic_rate >= 0 AND search_traffic_rate <= 1)",
            name="content_snapshot_search_rate_range",
        ),
        CheckConstraint(
            "recommendation_traffic_rate IS NULL OR "
            "(recommendation_traffic_rate >= 0 AND recommendation_traffic_rate <= 1)",
            name="content_snapshot_recommendation_rate_range",
        ),
        CheckConstraint(
            "profile_traffic_rate IS NULL OR "
            "(profile_traffic_rate >= 0 AND profile_traffic_rate <= 1)",
            name="content_snapshot_profile_rate_range",
        ),
        CheckConstraint(
            "source_kind IN ('live', 'imported', 'mock')",
            name="content_snapshot_source_kind",
        ),
        Index("ix_content_snapshots_content_captured", "content_item_id", "captured_at"),
        Index("ix_content_snapshots_captured_views", "captured_at", "view_count"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    content_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    share_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    favorite_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    follower_gain: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    average_watch_time: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    completion_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    search_traffic_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    recommendation_traffic_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8), nullable=True
    )
    profile_traffic_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    rpm: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_provider: Mapped[str] = mapped_column(String(120), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    content_item: Mapped[ContentItem] = relationship(back_populates="snapshots")


class DerivedMetric(Base):
    __tablename__ = "derived_metrics"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_id",
            "metric_key",
            "window",
            "calculated_at",
        ),
        CheckConstraint(
            "entity_type IN ('account', 'content_item')",
            name="derived_metric_entity_type",
        ),
        CheckConstraint(
            "metric_key IN ('view_growth_1h', 'view_growth_6h', 'view_growth_24h', "
            "'follower_growth_24h', 'engagement_rate', 'share_rate', 'favorite_rate', "
            "'view_velocity', 'view_acceleration', 'median_views_30d', "
            "'account_baseline_ratio', 'viral_score')",
            name="derived_metric_key",
        ),
        Index(
            "ix_derived_metrics_entity_metric_calculated",
            "entity_type",
            "entity_id",
            "metric_key",
            "calculated_at",
        ),
        Index("ix_derived_metrics_workspace_key_value", "workspace_id", "metric_key", "value"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    metric_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    window: Mapped[str] = mapped_column(String(32), nullable=False, default="current")
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


def reject_snapshot_mutation(_mapper: object, _connection: object, target: object) -> None:
    raise RuntimeError(
        f"{type(target).__name__} rows are append-only; insert a new captured_at snapshot"
    )


event.listen(AccountSnapshot, "before_update", reject_snapshot_mutation)
event.listen(ContentSnapshot, "before_update", reject_snapshot_mutation)
