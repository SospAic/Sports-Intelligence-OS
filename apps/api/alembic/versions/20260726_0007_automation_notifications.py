"""Add structured automations and encrypted notification channels.

Revision ID: 20260726_0007
Revises: 20260726_0006
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0007"
down_revision: str | None = "20260726_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "automation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("trigger_type", sa.String(64), nullable=False),
        sa.Column("condition_tree", sa.JSON(), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("deduplication_window", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("cooldown_seconds >= 0", name="automation_rule_cooldown"),
        sa.CheckConstraint("deduplication_window >= 0", name="automation_rule_dedup_window"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_automation_rules_workspace_id", ["workspace_id"]),
        ("ix_automation_rules_created_by", ["created_by"]),
        ("ix_automation_rules_entity_type", ["entity_type"]),
        ("ix_automation_rules_trigger_type", ["trigger_type"]),
        ("ix_automation_rules_workspace_enabled", ["workspace_id", "enabled", "priority"]),
    ):
        op.create_index(name, "automation_rules", columns)

    op.create_table(
        "automation_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "sort_order"),
    )
    for name, columns in (
        ("ix_automation_actions_workspace_id", ["workspace_id"]),
        ("ix_automation_actions_rule_id", ["rule_id"]),
        ("ix_automation_actions_workspace_rule", ["workspace_id", "rule_id"]),
    ):
        op.create_index(name, "automation_actions", columns)

    op.create_table(
        "automation_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched", sa.Boolean(), nullable=False),
        sa.Column("condition_result", sa.JSON(), nullable=False),
        sa.Column("deduplication_key", sa.String(255), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("execution_status", sa.String(32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "execution_status IN ('not_matched', 'suppressed', 'queued', 'completed', 'partial', 'failed')",
            name="automation_evaluation_status",
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "rule_id", "event_key"),
    )
    for name, columns in (
        ("ix_automation_evaluations_workspace_id", ["workspace_id"]),
        ("ix_automation_evaluations_rule_id", ["rule_id"]),
        ("ix_automation_evaluations_entity_type", ["entity_type"]),
        ("ix_automation_evaluations_entity_id", ["entity_id"]),
        ("ix_automation_evaluations_deduplication_key", ["deduplication_key"]),
        ("ix_automation_evaluations_rule_time", ["rule_id", "evaluated_at"]),
        (
            "ix_automation_evaluations_entity_time",
            ["entity_type", "entity_id", "evaluated_at"],
        ),
    ):
        op.create_index(name, "automation_evaluations", columns)

    op.create_table(
        "automation_runtime_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("consecutive_count", sa.Integer(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_deduplication_key", sa.String(255), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "entity_type", "entity_id"),
    )
    for name, columns in (
        ("ix_automation_runtime_states_workspace_id", ["workspace_id"]),
        ("ix_automation_runtime_states_rule_id", ["rule_id"]),
        ("ix_automation_runtime_cooldown", ["workspace_id", "cooldown_until"]),
    ):
        op.create_index(name, "automation_runtime_states", columns)

    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("config_encrypted", sa.Text(), nullable=False),
        sa.Column("config_masked", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'unhealthy')",
            name="notification_channel_health",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name"),
    )
    for name, columns in (
        ("ix_notification_channels_workspace_id", ["workspace_id"]),
        ("ix_notification_channels_provider_key", ["provider_key"]),
        ("ix_notification_channels_workspace_enabled", ["workspace_id", "enabled"]),
    ):
        op.create_index(name, "notification_channels", columns)

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('queued', 'sending', 'delivered', 'failed', 'cancelled')",
            name="notification_delivery_status",
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["notification_channels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_id"], ["automation_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    for name, columns in (
        ("ix_notification_deliveries_workspace_id", ["workspace_id"]),
        ("ix_notification_deliveries_channel_id", ["channel_id"]),
        ("ix_notification_deliveries_rule_id", ["rule_id"]),
        ("ix_notification_deliveries_entity_type", ["entity_type"]),
        ("ix_notification_deliveries_entity_id", ["entity_id"]),
        ("ix_notification_deliveries_status", ["status"]),
        ("ix_notification_deliveries_workspace_created", ["workspace_id", "created_at"]),
        ("ix_notification_deliveries_status_created", ["status", "created_at"]),
    ):
        op.create_index(name, "notification_deliveries", columns)


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notification_channels")
    op.drop_table("automation_runtime_states")
    op.drop_table("automation_evaluations")
    op.drop_table("automation_actions")
    op.drop_table("automation_rules")
