"""Create versioned editorial rule sets, sections, and structured rules.

Revision ID: 20260726_0005
Revises: 20260725_0004
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260726_0005"
down_revision: str | None = "20260725_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RULE_TYPES = (
    "principle",
    "qualification",
    "research",
    "narrative",
    "language",
    "structure",
    "fact_check",
    "length",
    "output",
    "qa",
    "rewrite",
    "tts",
    "ssml",
    "title",
    "search_keyword",
    "material_search",
)


def upgrade() -> None:
    op.create_table(
        "rule_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled', 'archived')", name="rule_set_status"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "key"),
    )
    op.create_index("ix_rule_sets_workspace_id", "rule_sets", ["workspace_id"])
    op.create_index("ix_rule_sets_current_version_id", "rule_sets", ["current_version_id"])
    op.create_index("ix_rule_sets_status", "rule_sets", ["status"])
    op.create_index("ix_rule_sets_workspace_status", "rule_sets", ["workspace_id", "status"])

    op.create_table(
        "rule_set_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="rule_set_version_status"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["rule_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_set_id", "version"),
    )
    for name, columns in (
        ("ix_rule_set_versions_workspace_id", ["workspace_id"]),
        ("ix_rule_set_versions_rule_set_id", ["rule_set_id"]),
        ("ix_rule_set_versions_source_hash", ["source_hash"]),
        ("ix_rule_set_versions_status", ["status"]),
        ("ix_rule_set_versions_created_by", ["created_by"]),
        ("ix_rule_set_versions_set_status", ["rule_set_id", "status"]),
        ("ix_rule_set_versions_workspace_created", ["workspace_id", "created_at"]),
    ):
        op.create_index(name, "rule_set_versions", columns)

    op.create_table(
        "rule_sections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["rule_sections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["rule_set_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "slug"),
    )
    for name, columns in (
        ("ix_rule_sections_workspace_id", ["workspace_id"]),
        ("ix_rule_sections_version_id", ["version_id"]),
        ("ix_rule_sections_parent_id", ["parent_id"]),
        ("ix_rule_sections_version_parent_order", ["version_id", "parent_id", "sort_order"]),
    ):
        op.create_index(name, "rule_sections", columns)

    rule_type_values = ",".join(f"'{item}'" for item in RULE_TYPES)
    op.create_table(
        "rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("why", sa.Text(), nullable=True),
        sa.Column("how", sa.Text(), nullable=True),
        sa.Column("good_example", sa.Text(), nullable=True),
        sa.Column("bad_example", sa.Text(), nullable=True),
        sa.Column("qa_check", sa.Text(), nullable=True),
        sa.Column("rewrite_instruction", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sports", sa.JSON(), nullable=False),
        sa.Column("story_types", sa.JSON(), nullable=False),
        sa.Column("output_types", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=True),
        sa.Column("source_status", sa.String(16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"rule_type IN ({rule_type_values})", name="editorial_rule_type"),
        sa.CheckConstraint("severity IN ('info', 'warning', 'error', 'critical')", name="editorial_rule_severity"),
        sa.CheckConstraint("priority >= 0 AND priority <= 100", name="editorial_rule_priority"),
        sa.CheckConstraint("source_status IN ('full', 'partial', 'unresolved')", name="editorial_rule_source_status"),
        sa.ForeignKeyConstraint(["section_id"], ["rule_sections.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id"], ["rule_set_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "key"),
    )
    for name, columns in (
        ("ix_rules_workspace_id", ["workspace_id"]),
        ("ix_rules_version_id", ["version_id"]),
        ("ix_rules_section_id", ["section_id"]),
        ("ix_rules_rule_type", ["rule_type"]),
        ("ix_rules_enabled", ["enabled"]),
        ("ix_rules_version_section_order", ["version_id", "section_id", "sort_order"]),
        ("ix_rules_version_type_enabled", ["version_id", "rule_type", "enabled"]),
        ("ix_rules_workspace_key", ["workspace_id", "key"]),
    ):
        op.create_index(name, "rules", columns)


def downgrade() -> None:
    op.drop_table("rules")
    op.drop_table("rule_sections")
    op.drop_table("rule_set_versions")
    op.drop_table("rule_sets")
