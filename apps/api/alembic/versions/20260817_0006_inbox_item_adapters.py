"""Allow the shared inbox to track review, alert and dead-letter records."""

from __future__ import annotations

from alembic import op

revision = "20260817_0006"
down_revision = "20260817_0005"
branch_labels = None
depends_on = None

_ITEM_KINDS = "'task', 'notification', 'editorial_comment', 'subscription_event', 'dead_letter'"


def upgrade() -> None:
    op.drop_constraint(
        "inbox_read_state_item_kind", "inbox_read_states", type_="check"
    )
    op.create_check_constraint(
        "inbox_read_state_item_kind",
        "inbox_read_states",
        f"item_kind IN ({_ITEM_KINDS})",
    )
    op.drop_constraint("inbox_queue_item_kind", "inbox_queue_states", type_="check")
    op.create_check_constraint(
        "inbox_queue_item_kind",
        "inbox_queue_states",
        f"item_kind IN ({_ITEM_KINDS})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "inbox_read_state_item_kind", "inbox_read_states", type_="check"
    )
    op.create_check_constraint(
        "inbox_read_state_item_kind",
        "inbox_read_states",
        "item_kind IN ('task', 'notification')",
    )
    op.drop_constraint("inbox_queue_item_kind", "inbox_queue_states", type_="check")
    op.create_check_constraint(
        "inbox_queue_item_kind",
        "inbox_queue_states",
        "item_kind IN ('task', 'notification')",
    )
