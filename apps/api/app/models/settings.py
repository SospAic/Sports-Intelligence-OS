from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LLMProviderSetting(TimestampMixin, Base):
    """Workspace-scoped encrypted connection settings for an LLM provider."""

    __tablename__ = "llm_provider_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_key"),
        Index("ix_llm_provider_settings_workspace_enabled", "workspace_id", "enabled"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    config_masked: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    default_model: Mapped[str] = mapped_column(String(160), nullable=False)
    default_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    input_cost_per_million: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    output_cost_per_million: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")


class SyncSettings(TimestampMixin, Base):
    """Workspace-scoped global fetch policy for platform synchronisation.

    Centralises the yt-dlp / scrape tuning that used to live per-account on
    ``accounts.adapter_config``. Every account in a workspace now shares one
    fetch policy: the works cap, the duplicate-skip behaviour and the
    yt-dlp window parameters (date range, playlist start, passthrough args).
    """

    __tablename__ = "sync_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class PlatformCredentialSetting(TimestampMixin, Base):
    """Workspace-scoped acquisition mode and encrypted platform credentials."""

    __tablename__ = "platform_credential_settings"
    __table_args__ = (
        UniqueConstraint("workspace_id", "platform_key"),
        Index(
            "ix_platform_credential_settings_workspace_enabled",
            "workspace_id",
            "enabled",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    config_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    config_masked: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
