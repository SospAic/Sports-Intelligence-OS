"""Allow play_follower_ratio derived metric key.

Adds the new relative metric (view_count / account follower count) to the
derived_metrics metric_key CHECK constraint. The frontend surfaces it as the
"播放 / 粉丝比" relative reach indicator.

Revision ID: 20260801_0020
Revises: 20260801_0019
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260801_0020"
down_revision: str | None = "20260801_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED_KEYS = (
    "'view_growth_1h', 'view_growth_6h', 'view_growth_24h', "
    "'follower_growth_24h', 'engagement_rate', 'share_rate', 'favorite_rate', "
    "'view_velocity', 'view_acceleration', 'median_views_30d', "
    "'account_baseline_ratio', 'play_follower_ratio', 'viral_score'"
)


def upgrade() -> None:
    op.drop_constraint("derived_metric_key", "derived_metrics", type_="check")
    op.create_check_constraint(
        "derived_metric_key",
        "derived_metrics",
        f"metric_key IN ({_ALLOWED_KEYS})",
    )


def downgrade() -> None:
    op.drop_constraint("derived_metric_key", "derived_metrics", type_="check")
    op.create_check_constraint(
        "derived_metric_key",
        "derived_metrics",
        "metric_key IN ('view_growth_1h', 'view_growth_6h', 'view_growth_24h', "
        "'follower_growth_24h', 'engagement_rate', 'share_rate', 'favorite_rate', "
        "'view_velocity', 'view_acceleration', 'median_views_30d', "
        "'account_baseline_ratio', 'viral_score')",
    )
