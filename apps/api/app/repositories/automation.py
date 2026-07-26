from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.automation import (
    AutomationEvaluation,
    AutomationRule,
    AutomationRuntimeState,
    NotificationChannel,
    NotificationDelivery,
)


class AutomationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rule(self, workspace_id: UUID, rule_id: UUID) -> AutomationRule | None:
        return cast(
            AutomationRule | None,
            await self.session.scalar(
                select(AutomationRule)
                .options(selectinload(AutomationRule.actions))
                .where(
                    AutomationRule.workspace_id == workspace_id,
                    AutomationRule.id == rule_id,
                )
            ),
        )

    async def list_rules(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        entity_type: str | None = None,
        enabled: bool | None = None,
    ) -> tuple[list[AutomationRule], int]:
        conditions = [AutomationRule.workspace_id == workspace_id]
        if entity_type:
            conditions.append(AutomationRule.entity_type == entity_type)
        if enabled is not None:
            conditions.append(AutomationRule.enabled.is_(enabled))
        statement = (
            select(AutomationRule)
            .where(*conditions)
            .order_by(AutomationRule.priority.desc(), AutomationRule.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self.session.scalars(statement)).all())
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(AutomationRule).where(*conditions)
                )
            )
            or 0
        )
        return items, total

    async def matching_rules(
        self, workspace_id: UUID, entity_type: str, trigger_type: str
    ) -> list[AutomationRule]:
        return list(
            (
                await self.session.scalars(
                    select(AutomationRule)
                    .options(selectinload(AutomationRule.actions))
                    .where(
                        AutomationRule.workspace_id == workspace_id,
                        AutomationRule.entity_type == entity_type,
                        AutomationRule.trigger_type == trigger_type,
                        AutomationRule.enabled.is_(True),
                    )
                    .order_by(AutomationRule.priority.desc())
                )
            ).all()
        )

    async def runtime_state(
        self, workspace_id: UUID, rule_id: UUID, entity_type: str, entity_id: UUID
    ) -> AutomationRuntimeState | None:
        return cast(
            AutomationRuntimeState | None,
            await self.session.scalar(
                select(AutomationRuntimeState).where(
                    AutomationRuntimeState.workspace_id == workspace_id,
                    AutomationRuntimeState.rule_id == rule_id,
                    AutomationRuntimeState.entity_type == entity_type,
                    AutomationRuntimeState.entity_id == entity_id,
                )
            ),
        )

    async def evaluation_by_event(
        self, workspace_id: UUID, rule_id: UUID, event_key: str
    ) -> AutomationEvaluation | None:
        return cast(
            AutomationEvaluation | None,
            await self.session.scalar(
                select(AutomationEvaluation).where(
                    AutomationEvaluation.workspace_id == workspace_id,
                    AutomationEvaluation.rule_id == rule_id,
                    AutomationEvaluation.event_key == event_key,
                )
            ),
        )

    async def list_evaluations(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        rule_id: UUID | None = None,
        matched: bool | None = None,
        evaluated_from: datetime | None = None,
    ) -> tuple[list[AutomationEvaluation], int]:
        conditions = [AutomationEvaluation.workspace_id == workspace_id]
        if rule_id:
            conditions.append(AutomationEvaluation.rule_id == rule_id)
        if matched is not None:
            conditions.append(AutomationEvaluation.matched.is_(matched))
        if evaluated_from is not None:
            conditions.append(AutomationEvaluation.evaluated_at >= evaluated_from)
        items = list(
            (
                await self.session.scalars(
                    select(AutomationEvaluation)
                    .where(*conditions)
                    .order_by(AutomationEvaluation.evaluated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(AutomationEvaluation).where(*conditions)
                )
            )
            or 0
        )
        return items, total

    async def channel(self, workspace_id: UUID, channel_id: UUID) -> NotificationChannel | None:
        return cast(
            NotificationChannel | None,
            await self.session.scalar(
                select(NotificationChannel).where(
                    NotificationChannel.workspace_id == workspace_id,
                    NotificationChannel.id == channel_id,
                )
            ),
        )

    async def list_channels(self, workspace_id: UUID) -> list[NotificationChannel]:
        return list(
            (
                await self.session.scalars(
                    select(NotificationChannel)
                    .where(NotificationChannel.workspace_id == workspace_id)
                    .order_by(NotificationChannel.name)
                )
            ).all()
        )

    async def delivery(self, workspace_id: UUID, delivery_id: UUID) -> NotificationDelivery | None:
        return cast(
            NotificationDelivery | None,
            await self.session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.workspace_id == workspace_id,
                    NotificationDelivery.id == delivery_id,
                )
            ),
        )

    async def delivery_by_key(
        self, workspace_id: UUID, idempotency_key: str
    ) -> NotificationDelivery | None:
        return cast(
            NotificationDelivery | None,
            await self.session.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.workspace_id == workspace_id,
                    NotificationDelivery.idempotency_key == idempotency_key,
                )
            ),
        )

    async def list_deliveries(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        channel_id: UUID | None = None,
    ) -> tuple[list[NotificationDelivery], int]:
        conditions = [NotificationDelivery.workspace_id == workspace_id]
        if status:
            conditions.append(NotificationDelivery.status == status)
        if channel_id:
            conditions.append(NotificationDelivery.channel_id == channel_id)
        items = list(
            (
                await self.session.scalars(
                    select(NotificationDelivery)
                    .where(*conditions)
                    .order_by(NotificationDelivery.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(NotificationDelivery).where(*conditions)
                )
            )
            or 0
        )
        return items, total
