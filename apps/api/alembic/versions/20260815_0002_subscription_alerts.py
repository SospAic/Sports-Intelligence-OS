"""Add auditable account/content subscriptions and alert queue linkage."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260815_0002"
down_revision = "20260815_0001"
branch_labels = None
depends_on = None


def _json_default(value: str) -> sa.TextClause:
    return sa.text(f"'{value}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "subscription_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="new_content"),
        sa.Column("platform_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("keywords", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=_json_default("[]")),
        sa.Column("thresholds", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=_json_default("{}")),
        sa.Column("channel_ids", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=_json_default("[]")),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "trigger_type IN ('new_content', 'keyword_match', 'metric_spike')",
            name="subscription_rule_trigger_type",
        ),
        sa.CheckConstraint("cooldown_seconds >= 0", name="subscription_rule_cooldown"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["platform_id"], ["platforms.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_subscription_rules_workspace_name"),
    )
    for index_name, columns in (
        ("ix_subscription_rules_workspace_id", ["workspace_id"]),
        ("ix_subscription_rules_created_by", ["created_by"]),
        ("ix_subscription_rules_platform_id", ["platform_id"]),
        ("ix_subscription_rules_account_id", ["account_id"]),
        ("ix_subscription_rules_enabled", ["enabled"]),
        ("ix_subscription_rules_workspace_enabled", ["workspace_id", "enabled", "priority"]),
        ("ix_subscription_rules_target", ["workspace_id", "account_id", "platform_id", "enabled"]),
    ):
        op.create_index(index_name, "subscription_rules", columns)
    op.alter_column("subscription_rules", "trigger_type", server_default=None)
    op.alter_column("subscription_rules", "keywords", server_default=None)
    op.alter_column("subscription_rules", "thresholds", server_default=None)
    op.alter_column("subscription_rules", "channel_ids", server_default=None)
    op.alter_column("subscription_rules", "cooldown_seconds", server_default=None)
    op.alter_column("subscription_rules", "priority", server_default=None)
    op.alter_column("subscription_rules", "enabled", server_default=None)

    op.create_table(
        "subscription_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=_json_default("{}")),
        sa.Column("delivery_ids", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False, server_default=_json_default("[]")),
        sa.CheckConstraint(
            "status IN ('not_matched', 'suppressed', 'queued', 'partial', 'failed')",
            name="subscription_event_status",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscription_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "subscription_id", "event_key", name="uq_subscription_events_event_key"
        ),
    )
    for index_name, columns in (
        ("ix_subscription_events_workspace_id", ["workspace_id"]),
        ("ix_subscription_events_subscription_id", ["subscription_id"]),
        ("ix_subscription_events_entity_id", ["entity_id"]),
        ("ix_subscription_events_subscription_time", ["subscription_id", "evaluated_at"]),
        ("ix_subscription_events_entity_time", ["entity_type", "entity_id", "evaluated_at"]),
    ):
        op.create_index(index_name, "subscription_events", columns)
    op.alter_column("subscription_events", "details", server_default=None)
    op.alter_column("subscription_events", "delivery_ids", server_default=None)

    op.add_column(
        "notification_deliveries",
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_notification_deliveries_subscription_id_subscription_rules",
        "notification_deliveries",
        "subscription_rules",
        ["subscription_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notification_deliveries_subscription_id",
        "notification_deliveries",
        ["subscription_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_deliveries_subscription_id", table_name="notification_deliveries")
    op.drop_constraint(
        "fk_notification_deliveries_subscription_id_subscription_rules",
        "notification_deliveries",
        type_="foreignkey",
    )
    op.drop_column("notification_deliveries", "subscription_id")
    for index_name in (
        "ix_subscription_events_entity_time",
        "ix_subscription_events_subscription_time",
        "ix_subscription_events_entity_id",
        "ix_subscription_events_subscription_id",
        "ix_subscription_events_workspace_id",
    ):
        op.drop_index(index_name, table_name="subscription_events")
    op.drop_table("subscription_events")
    for index_name in (
        "ix_subscription_rules_target",
        "ix_subscription_rules_workspace_enabled",
        "ix_subscription_rules_enabled",
        "ix_subscription_rules_account_id",
        "ix_subscription_rules_platform_id",
        "ix_subscription_rules_created_by",
        "ix_subscription_rules_workspace_id",
    ):
        op.drop_index(index_name, table_name="subscription_rules")
    op.drop_table("subscription_rules")
