"""reliability and discovery tables

Revision ID: 20260728_0012
Revises: 7b47d6cd3a45
Create Date: 2026-07-28 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260728_0012"
down_revision = "7b47d6cd3a45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Outbox event attempts (per-publish-attempt records) ──────────
    op.create_table(
        "outbox_event_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("outbox_event_id", sa.Uuid(), sa.ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("consumer", sa.String(120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_detail_safe", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('success', 'failed', 'timeout')", name="outbox_attempt_status"),
    )
    op.create_index("ix_outbox_attempts_event_number", "outbox_event_attempts", ["outbox_event_id", "attempt_number"])

    # ── Dead letter events (permanently failed outbox events) ────────
    op.create_table(
        "dead_letter_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("outbox_event_id", sa.Uuid(), sa.ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("event_type", sa.String(160), nullable=False, index=True),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("original_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("replay_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("replay_status IN ('pending', 'replaying', 'replayed', 'discarded')", name="dead_letter_replay_status"),
    )

    # ── Notification delivery attempts (per-send-attempt records) ────
    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("delivery_id", sa.Uuid(), sa.ForeignKey("notification_deliveries.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("notification_channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_key", sa.String(80), nullable=True),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_detail_safe", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("request_summary", sa.JSON(), nullable=True),
        sa.Column("response_summary", sa.JSON(), nullable=True),
        sa.CheckConstraint("status IN ('success', 'failed', 'timeout')", name="delivery_attempt_status"),
    )
    op.create_index("ix_delivery_attempts_delivery_number", "notification_delivery_attempts", ["delivery_id", "attempt_number"])

    # ── External call attempts (generic per-call logging) ────────────
    op.create_table(
        "external_call_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True, index=True),
        sa.Column("call_type", sa.String(64), nullable=False, index=True),
        sa.Column("provider_key", sa.String(80), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("target_url", sa.String(2048), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_detail_safe", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("request_summary", sa.JSON(), nullable=True),
        sa.Column("response_summary", sa.JSON(), nullable=True),
        sa.CheckConstraint("status IN ('success', 'failed', 'timeout')", name="external_call_status"),
        sa.CheckConstraint("call_type IN ('notification', 'webhook', 'news_sync', 'platform_api', 'llm', 'other')", name="external_call_type"),
    )
    op.create_index("ix_external_calls_provider_time", "external_call_attempts", ["provider_key", "started_at"])
    op.create_index("ix_external_calls_workspace_time", "external_call_attempts", ["workspace_id", "started_at"])

    # ── Notification templates ───────────────────────────────────────
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(64), nullable=False, server_default="general"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "name"),
    )

    # ── Notification template versions ───────────────────────────────
    op.create_table(
        "notification_template_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("notification_templates.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("subject_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("variables_schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("change_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("template_id", "version"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="template_version_status"),
    )

    # ── Dashboard aggregated stats (materialized summaries) ──────────
    op.create_table(
        "dashboard_stats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stat_key", sa.String(120), nullable=False),
        sa.Column("stat_value", sa.JSON(), nullable=False),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "stat_key", "period"),
    )


def downgrade() -> None:
    op.drop_table("dashboard_stats")
    op.drop_table("notification_template_versions")
    op.drop_table("notification_templates")
    op.drop_table("external_call_attempts")
    op.drop_table("notification_delivery_attempts")
    op.drop_table("dead_letter_events")
    op.drop_table("outbox_event_attempts")
