"""Create trend storage and encrypted platform credential settings.

Revision ID: 20260729_0013
Revises: 20260728_0012
Create Date: 2026-07-29 12:00:00.000000
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from alembic import op
from app.providers.notifications.crypto import SecretConfigCipher, mask_secret_config

revision = "20260729_0013"
down_revision = "20260728_0012"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def _legacy_mode(config: dict[str, Any], platform_key: str) -> tuple[str, bool]:
    if config.get("storage_state_json"):
        config.update(
            account_authorization_confirmed="true",
            platform_session_allowed="true",
            oauth_unavailable_or_insufficient="true",
        )
        return "authorized_session", True
    if config.get("username") and config.get("password"):
        config.update(
            account_authorization_confirmed="true",
            platform_login_allowed="true",
            oauth_unavailable_or_insufficient="true",
        )
        return "authorized_login", True
    required_api_fields = {
        "youtube": {"api_key"},
        "tiktok": {"client_key", "client_secret", "access_token"},
        "douyin": {"client_key", "client_secret", "access_token"},
    }
    required = required_api_fields.get(platform_key)
    if required and all(config.get(field) for field in required):
        return "api", True
    return "public_page", False


def _masked_platform_config(config: dict[str, Any]) -> dict[str, Any]:
    safe = mask_secret_config(
        {
            key: value
            for key, value in config.items()
            if key not in {"username", "storage_state_json", "legacy_account_configs"}
        }
    )
    for field in ("username", "storage_state_json", "legacy_account_configs"):
        if config.get(field):
            safe[field] = "configured"
    return safe


def _migrate_legacy_account_configs() -> None:
    """Encrypt legacy account metadata before removing its plaintext copy."""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT a.id AS account_id, a.workspace_id, p.key AS platform_key, "
            "a.metadata::jsonb -> 'adapter_config' AS config "
            "FROM accounts a JOIN platforms p ON p.id = a.platform_id "
            "WHERE a.metadata::jsonb ? 'adapter_config'"
        )
    ).mappings()
    grouped: dict[tuple[Any, str], list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
    for row in rows:
        raw = row["config"]
        config = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        config.pop("mode", None)
        grouped[(row["workspace_id"], row["platform_key"])].append((row["account_id"], config))
    if not grouped:
        return

    encryption_material = os.getenv("SIO_NOTIFICATION_ENCRYPTION_KEY") or os.getenv(
        "SIO_SECRET_KEY"
    )
    if not encryption_material:
        raise RuntimeError(
            "SIO_SECRET_KEY or SIO_NOTIFICATION_ENCRYPTION_KEY is required to migrate "
            "legacy platform credentials"
        )
    cipher = SecretConfigCipher(encryption_material)
    credential_table = sa.table(
        "platform_credential_settings",
        sa.column("id", sa.Uuid()),
        sa.column("workspace_id", sa.Uuid()),
        sa.column("platform_key", sa.String()),
        sa.column("mode", sa.String()),
        sa.column("config_encrypted", sa.Text()),
        sa.column("config_masked", sa.JSON()),
        sa.column("enabled", sa.Boolean()),
    )
    for (workspace_id, platform_key), account_configs in grouped.items():
        config = dict(account_configs[0][1])
        if len(account_configs) > 1:
            config["legacy_account_configs"] = {
                str(account_id): account_config for account_id, account_config in account_configs
            }
        mode, enabled = _legacy_mode(config, platform_key)
        existing = bind.execute(
            sa.select(credential_table.c.id).where(
                credential_table.c.workspace_id == workspace_id,
                credential_table.c.platform_key == platform_key,
            )
        ).scalar_one_or_none()
        if existing is None:
            bind.execute(
                credential_table.insert().values(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    platform_key=platform_key,
                    mode=mode,
                    config_encrypted=cipher.encrypt(config),
                    config_masked=_masked_platform_config(config),
                    enabled=enabled,
                )
            )

    bind.execute(
        sa.text(
            "UPDATE accounts "
            "SET metadata = ((metadata::jsonb - 'adapter_config')::json) "
            "WHERE metadata::jsonb ? 'adapter_config'"
        )
    )


def upgrade() -> None:
    if not _table_exists("platform_credential_settings"):
        op.create_table(
            "platform_credential_settings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("platform_key", sa.String(64), nullable=False),
            sa.Column("mode", sa.String(32), nullable=False),
            sa.Column("config_encrypted", sa.Text(), nullable=False),
            sa.Column("config_masked", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "platform_key"),
        )
    _create_index_if_missing(
        "ix_platform_credential_settings_workspace_id",
        "platform_credential_settings",
        ["workspace_id"],
    )
    _create_index_if_missing(
        "ix_platform_credential_settings_platform_key",
        "platform_credential_settings",
        ["platform_key"],
    )
    _create_index_if_missing(
        "ix_platform_credential_settings_workspace_enabled",
        "platform_credential_settings",
        ["workspace_id", "enabled"],
    )

    if not _table_exists("trend_topics"):
        op.create_table(
            "trend_topics",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("category", sa.String(100), nullable=False),
            sa.Column("heat_score", sa.Float(), nullable=False),
            sa.Column("growth_rate", sa.Float(), nullable=True),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("sample_size", sa.Integer(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_trend_topics_workspace_id", "trend_topics", ["workspace_id"])
    _create_index_if_missing("ix_trend_topics_platform", "trend_topics", ["platform"])
    _create_index_if_missing(
        "ix_trend_topics_workspace_platform", "trend_topics", ["workspace_id", "platform"]
    )
    _create_index_if_missing(
        "ix_trend_topics_workspace_title", "trend_topics", ["workspace_id", "title"]
    )
    _create_index_if_missing("ix_trend_topics_observed_at", "trend_topics", ["observed_at"])

    if not _table_exists("trend_videos"):
        op.create_table(
            "trend_videos",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("external_id", sa.String(255), nullable=False),
            sa.Column("title", sa.String(1000), nullable=False),
            sa.Column("author_name", sa.String(255), nullable=True),
            sa.Column("author_url", sa.String(1000), nullable=True),
            sa.Column("cover_url", sa.String(2000), nullable=True),
            sa.Column("video_url", sa.String(2000), nullable=True),
            sa.Column("view_count", sa.BigInteger(), nullable=True),
            sa.Column("like_count", sa.BigInteger(), nullable=True),
            sa.Column("comment_count", sa.BigInteger(), nullable=True),
            sa.Column("share_count", sa.BigInteger(), nullable=True),
            sa.Column("breakout_score", sa.Float(), nullable=True),
            sa.Column("category", sa.String(100), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_trend_videos_workspace_id", "trend_videos", ["workspace_id"])
    _create_index_if_missing("ix_trend_videos_platform", "trend_videos", ["platform"])
    _create_index_if_missing("ix_trend_videos_external_id", "trend_videos", ["external_id"])
    _create_index_if_missing(
        "ix_trend_videos_workspace_platform", "trend_videos", ["workspace_id", "platform"]
    )
    _create_index_if_missing("ix_trend_videos_observed_at", "trend_videos", ["observed_at"])
    _create_index_if_missing("ix_trend_videos_breakout", "trend_videos", ["breakout_score"])

    if not _table_exists("trend_keyword_snapshots"):
        op.create_table(
            "trend_keyword_snapshots",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("keyword", sa.String(200), nullable=False),
            sa.Column("platform", sa.String(32), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("video_count", sa.Integer(), nullable=True),
            sa.Column("total_views", sa.BigInteger(), nullable=True),
            sa.Column("avg_views", sa.Float(), nullable=True),
            sa.Column("heat_index", sa.Float(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            *_timestamps(),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id",
                "keyword",
                "platform",
                "observed_at",
                name="uq_trend_kw_ws_kw_plat_time",
            ),
        )
    _create_index_if_missing(
        "ix_trend_keyword_snapshots_workspace_id", "trend_keyword_snapshots", ["workspace_id"]
    )
    _create_index_if_missing(
        "ix_trend_keyword_snapshots_keyword", "trend_keyword_snapshots", ["keyword"]
    )
    _create_index_if_missing(
        "ix_trend_keyword_snapshots_platform", "trend_keyword_snapshots", ["platform"]
    )
    _create_index_if_missing(
        "ix_trend_kw_workspace_platform",
        "trend_keyword_snapshots",
        ["workspace_id", "platform"],
    )
    _migrate_legacy_account_configs()


def downgrade() -> None:
    op.drop_table("trend_keyword_snapshots")
    op.drop_table("trend_videos")
    op.drop_table("trend_topics")
    op.drop_table("platform_credential_settings")
