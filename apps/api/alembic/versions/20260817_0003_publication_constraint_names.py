"""Normalize publication attribution constraint names for Alembic stability."""

from __future__ import annotations

from alembic import op

revision = "20260817_0003"
down_revision = "20260817_0002"
branch_labels = None
depends_on = None


def _rename_if_present(old: str, new: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'performance_attributions'::regclass
                  AND conname = '{old}'
            ) THEN
                ALTER TABLE performance_attributions RENAME CONSTRAINT "{old}" TO "{new}";
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_source_kind",
        "pat_source_kind",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_window_key",
        "pat_window_key",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_com_e612",
        "pat_comments_nonnegative",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_fav_2987",
        "pat_favorites_nonnegative",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_lik_6f57",
        "pat_likes_nonnegative",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_mea_b888",
        "pat_measurement_status",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_sha_aa58",
        "pat_shares_nonnegative",
    )
    _rename_if_present(
        "ck_performance_attributions_performance_attribution_vie_c3c4",
        "pat_views_nonnegative",
    )


def downgrade() -> None:
    # Constraint names are an implementation detail; keeping the normalized
    # names on downgrade is safer than recreating PostgreSQL's truncation hash.
    return None
