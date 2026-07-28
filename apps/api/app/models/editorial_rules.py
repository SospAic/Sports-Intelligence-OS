from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

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


class RuleSet(TimestampMixin, Base):
    __tablename__ = "rule_sets"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled', 'archived')", name="rule_set_status"),
        UniqueConstraint("workspace_id", "key"),
        Index("ix_rule_sets_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deliberately validated in the service rather than declared as a circular FK.
    current_version_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    versions: Mapped[list[RuleSetVersion]] = relationship(
        back_populates="rule_set",
        cascade="all, delete-orphan",
        foreign_keys="RuleSetVersion.rule_set_id",
    )


class RuleSetVersion(Base):
    __tablename__ = "rule_set_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name="rule_set_version_status"
        ),
        UniqueConstraint("rule_set_id", "version"),
        Index("ix_rule_set_versions_set_status", "rule_set_id", "status"),
        Index("ix_rule_set_versions_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rule_set: Mapped[RuleSet] = relationship(back_populates="versions", foreign_keys=[rule_set_id])
    sections: Mapped[list[RuleSection]] = relationship(
        back_populates="version", cascade="all, delete-orphan"
    )
    rules: Mapped[list[Rule]] = relationship(back_populates="version", cascade="all, delete-orphan")


class RuleSection(Base):
    __tablename__ = "rule_sections"
    __table_args__ = (
        UniqueConstraint("version_id", "slug"),
        Index("ix_rule_sections_version_parent_order", "version_id", "parent_id", "sort_order"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_set_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rule_sections.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(2000), nullable=False)
    slug: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    version: Mapped[RuleSetVersion] = relationship(back_populates="sections")
    parent: Mapped[RuleSection | None] = relationship(
        remote_side="RuleSection.id", back_populates="children"
    )
    children: Mapped[list[RuleSection]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    rules: Mapped[list[Rule]] = relationship(back_populates="section", cascade="all, delete-orphan")


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint(
            "rule_type IN (" + ",".join(f"'{item}'" for item in RULE_TYPES) + ")",
            name="editorial_rule_type",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error', 'critical')",
            name="editorial_rule_severity",
        ),
        CheckConstraint("priority >= 0 AND priority <= 100", name="editorial_rule_priority"),
        CheckConstraint(
            "source_status IN ('full', 'partial', 'unresolved')",
            name="editorial_rule_source_status",
        ),
        UniqueConstraint("version_id", "key"),
        Index("ix_rules_version_section_order", "version_id", "section_id", "sort_order"),
        Index("ix_rules_version_type_enabled", "version_id", "rule_type", "enabled"),
        Index("ix_rules_workspace_key", "workspace_id", "key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_set_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[UUID] = mapped_column(
        ForeignKey("rule_sections.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    why: Mapped[str | None] = mapped_column(Text, nullable=True)
    how: Mapped[str | None] = mapped_column(Text, nullable=True)
    good_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    bad_example: Mapped[str | None] = mapped_column(Text, nullable=True)
    qa_check: Mapped[str | None] = mapped_column(Text, nullable=True)
    rewrite_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    sports: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    story_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    output_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dependencies: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    conflicts: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_status: Mapped[str] = mapped_column(String(16), nullable=False, default="full")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    version: Mapped[RuleSetVersion] = relationship(back_populates="rules")
    section: Mapped[RuleSection] = relationship(back_populates="rules")
