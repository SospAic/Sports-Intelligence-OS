"""Add code-level + business-level error detail to the operation trail.

The system operation trail (system events, audit entries, external call
attempts, background task runs, outbox/dead-letter attempts, news + generation
runs) records failures, but only some tables carried a raw code-level string and
none carried a business-layer explanation. This migration adds the missing
columns so every error in the trail can surface both:

- ``error_detail`` / ``error_detail_safe`` — the code-level detail (exception
  class, message, adapter, run/request ids) for developer debugging.
- ``error_hint`` — the business-layer explanation + remediation mapped from the
  error code, so operators know what to do next.

``audit_entries`` additionally gains a ``status`` ('success' | 'failed') so a
failed audited operation can be recorded as such. All new columns are nullable
or carry a safe default so existing rows are unaffected.

Revision ID: 20260803_0001
Revises: 20260802_0030
Create Date: 2026-08-03 00:01:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_0001"
down_revision = "20260802_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- system_events: structured error fields -------------------------
    op.add_column("system_events", sa.Column("error_code", sa.String(120), nullable=True))
    op.add_column("system_events", sa.Column("error_detail", sa.Text(), nullable=True))
    op.add_column("system_events", sa.Column("error_hint", sa.Text(), nullable=True))

    # --- audit_entries: status + structured error fields ----------------
    op.add_column(
        "audit_entries",
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="success",
        ),
    )
    op.create_check_constraint(
        "ck_audit_entries_status",
        "audit_entries",
        "status IN ('success', 'failed')",
    )
    op.add_column("audit_entries", sa.Column("error_code", sa.String(120), nullable=True))
    op.add_column("audit_entries", sa.Column("error_detail", sa.Text(), nullable=True))
    op.add_column("audit_entries", sa.Column("error_hint", sa.Text(), nullable=True))

    # --- external_call_attempts: business hint --------------------------
    op.add_column("external_call_attempts", sa.Column("error_hint", sa.Text(), nullable=True))

    # --- task_runs: business hint ---------------------------------------
    op.add_column("task_runs", sa.Column("error_hint", sa.Text(), nullable=True))

    # --- outbox_event_attempts: business hint ---------------------------
    op.add_column("outbox_event_attempts", sa.Column("error_hint", sa.Text(), nullable=True))

    # --- dead_letter_events: business hint ------------------------------
    op.add_column("dead_letter_events", sa.Column("last_error_hint", sa.Text(), nullable=True))

    # --- news_sync_runs: code-level + business hint ---------------------
    op.add_column("news_sync_runs", sa.Column("error_detail", sa.Text(), nullable=True))
    op.add_column("news_sync_runs", sa.Column("error_hint", sa.Text(), nullable=True))

    # --- generation_runs: business hint --------------------------------
    op.add_column("generation_runs", sa.Column("error_hint", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_runs", "error_hint")
    op.drop_column("news_sync_runs", "error_hint")
    op.drop_column("news_sync_runs", "error_detail")
    op.drop_column("dead_letter_events", "last_error_hint")
    op.drop_column("outbox_event_attempts", "error_hint")
    op.drop_column("task_runs", "error_hint")
    op.drop_column("external_call_attempts", "error_hint")
    op.drop_column("audit_entries", "error_hint")
    op.drop_column("audit_entries", "error_detail")
    op.drop_column("audit_entries", "error_code")
    op.drop_constraint("ck_audit_entries_status", "audit_entries", type_="check")
    op.drop_column("audit_entries", "status")
    op.drop_column("system_events", "error_hint")
    op.drop_column("system_events", "error_detail")
    op.drop_column("system_events", "error_code")
