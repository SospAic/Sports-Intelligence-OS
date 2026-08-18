"""Add notification template indexes declared on the models.

The models ``notification_template.py`` declared two indexes that were never
emitted by a migration:

- ``ix_notification_templates_workspace_category`` on
  ``notification_templates(workspace_id, category)``
- ``ix_template_versions_template_status`` on
  ``notification_template_versions(template_id, status)``

Without this migration, ``alembic upgrade head`` (the production path) skips
these indexes while ``Base.metadata.create_all`` (the test path) creates them,
leaving the two environments inconsistent. ``if_not_exists`` keeps the
migration idempotent for databases that were previously created via
``create_all``.

Revision ID: 20260801_0024
Revises: 20260801_0023
Create Date: 2026-08-01 12:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "20260801_0024"
down_revision = "20260801_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_notification_templates_workspace_category",
        "notification_templates",
        ["workspace_id", "category"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_template_versions_template_status",
        "notification_template_versions",
        ["template_id", "status"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_template_versions_template_status",
        table_name="notification_template_versions",
        if_exists=True,
    )
    op.drop_index(
        "ix_notification_templates_workspace_category",
        table_name="notification_templates",
        if_exists=True,
    )
