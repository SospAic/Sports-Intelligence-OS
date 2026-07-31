from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.editorial_rules import Rule, RuleSet, RuleSetVersion


@dataclass(frozen=True)
class RuleSetRow:
    rule_set: RuleSet
    version_count: int
    draft_count: int


class EditorialRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rule_set(self, workspace_id: UUID, rule_set_id: UUID) -> RuleSet | None:
        return cast(
            RuleSet | None,
            await self.session.scalar(
                select(RuleSet).where(
                    RuleSet.workspace_id == workspace_id, RuleSet.id == rule_set_id
                )
            ),
        )

    async def rule_set_by_key(self, workspace_id: UUID, key: str) -> RuleSet | None:
        return cast(
            RuleSet | None,
            await self.session.scalar(
                select(RuleSet).where(RuleSet.workspace_id == workspace_id, RuleSet.key == key)
            ),
        )

    async def list_rule_sets(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        query: str | None,
        status: str | None,
    ) -> tuple[list[RuleSetRow], int]:
        conditions = [RuleSet.workspace_id == workspace_id]
        if query:
            pattern = f"%{query.casefold()}%"
            conditions.append(
                or_(func.lower(RuleSet.name).like(pattern), func.lower(RuleSet.key).like(pattern))
            )
        if status:
            conditions.append(RuleSet.status == status)
        version_count = (
            select(func.count(RuleSetVersion.id))
            .where(RuleSetVersion.rule_set_id == RuleSet.id)
            .correlate(RuleSet)
            .scalar_subquery()
        )
        draft_count = (
            select(func.count(RuleSetVersion.id))
            .where(
                RuleSetVersion.rule_set_id == RuleSet.id,
                RuleSetVersion.status == "draft",
            )
            .correlate(RuleSet)
            .scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(RuleSet, version_count, draft_count)
                .where(*conditions)
                .order_by(RuleSet.updated_at.desc(), RuleSet.name.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(RuleSet).where(*conditions)
                )
            )
            or 0
        )
        return [RuleSetRow(row[0], int(row[1]), int(row[2])) for row in rows], total

    async def versions(self, workspace_id: UUID, rule_set_id: UUID) -> list[RuleSetVersion]:
        return list(
            (
                await self.session.scalars(
                    select(RuleSetVersion)
                    .where(
                        RuleSetVersion.workspace_id == workspace_id,
                        RuleSetVersion.rule_set_id == rule_set_id,
                    )
                    .order_by(RuleSetVersion.created_at.desc())
                )
            ).all()
        )

    async def version(
        self, workspace_id: UUID, rule_set_id: UUID, version_id: UUID
    ) -> RuleSetVersion | None:
        return cast(
            RuleSetVersion | None,
            await self.session.scalar(
                select(RuleSetVersion)
                .options(
                    selectinload(RuleSetVersion.sections),
                    selectinload(RuleSetVersion.rules),
                )
                .where(
                    RuleSetVersion.workspace_id == workspace_id,
                    RuleSetVersion.rule_set_id == rule_set_id,
                    RuleSetVersion.id == version_id,
                )
            ),
        )

    async def version_by_label(
        self, workspace_id: UUID, rule_set_id: UUID, version: str
    ) -> RuleSetVersion | None:
        return cast(
            RuleSetVersion | None,
            await self.session.scalar(
                select(RuleSetVersion).where(
                    RuleSetVersion.workspace_id == workspace_id,
                    RuleSetVersion.rule_set_id == rule_set_id,
                    RuleSetVersion.version == version,
                )
            ),
        )

    async def version_by_hash(
        self, workspace_id: UUID, rule_set_id: UUID, source_hash: str
    ) -> RuleSetVersion | None:
        return cast(
            RuleSetVersion | None,
            await self.session.scalar(
                select(RuleSetVersion)
                .options(
                    selectinload(RuleSetVersion.sections),
                    selectinload(RuleSetVersion.rules),
                )
                .where(
                    RuleSetVersion.workspace_id == workspace_id,
                    RuleSetVersion.rule_set_id == rule_set_id,
                    RuleSetVersion.source_hash == source_hash,
                )
                .order_by(RuleSetVersion.created_at.asc())
            ),
        )

    async def rule(self, workspace_id: UUID, version_id: UUID, rule_id: UUID) -> Rule | None:
        return cast(
            Rule | None,
            await self.session.scalar(
                select(Rule).where(
                    Rule.workspace_id == workspace_id,
                    Rule.version_id == version_id,
                    Rule.id == rule_id,
                )
            ),
        )

    async def rules(
        self,
        workspace_id: UUID,
        version_id: UUID,
        *,
        query: str | None,
        rule_type: str | None,
        is_mandatory: bool | None,
        enabled: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Rule], int]:
        conditions = [Rule.workspace_id == workspace_id, Rule.version_id == version_id]
        if query:
            pattern = f"%{query.casefold()}%"
            conditions.append(
                or_(
                    func.lower(Rule.key).like(pattern),
                    func.lower(Rule.title).like(pattern),
                    func.lower(Rule.instruction).like(pattern),
                )
            )
        if rule_type:
            conditions.append(Rule.rule_type == rule_type)
        if is_mandatory is not None:
            conditions.append(Rule.is_mandatory.is_(is_mandatory))
        if enabled is not None:
            conditions.append(Rule.enabled.is_(enabled))
        items = list(
            (
                await self.session.scalars(
                    select(Rule)
                    .where(*conditions)
                    .order_by(Rule.sort_order.asc(), Rule.key.asc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (await self.session.scalar(select(func.count()).select_from(Rule).where(*conditions)))
            or 0
        )
        return items, total
