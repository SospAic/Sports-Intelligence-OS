"""Align the remaining fixed-window constraint names with the ORM model."""

from __future__ import annotations

from alembic import op

revision = "20260817_0004"
down_revision = "20260817_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'performance_attributions'::regclass
                  AND conname = 'ck_performance_attributions_performance_attribution_source_kind'
            ) THEN
                ALTER TABLE performance_attributions
                RENAME CONSTRAINT "ck_performance_attributions_performance_attribution_source_kind"
                TO "pat_source_kind";
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'performance_attributions'::regclass
                  AND conname = 'ck_performance_attributions_performance_attribution_window_key'
            ) THEN
                ALTER TABLE performance_attributions
                RENAME CONSTRAINT "ck_performance_attributions_performance_attribution_window_key"
                TO "pat_window_key";
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Keep normalized names when rolling back; constraint names are not data.
    return None
