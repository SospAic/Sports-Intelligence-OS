from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topics import SavedTopic


class TopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
        source_type: str | None,
        query: str | None,
    ) -> tuple[list[SavedTopic], int]:
        filters = [SavedTopic.workspace_id == workspace_id]
        if status:
            filters.append(SavedTopic.status == status)
        if source_type:
            filters.append(SavedTopic.source_type == source_type)
        if query:
            pattern = f"%{query.strip()}%"
            filters.append(or_(SavedTopic.title.ilike(pattern), SavedTopic.summary.ilike(pattern)))
        total = int(
            await self.session.scalar(select(func.count()).select_from(SavedTopic).where(*filters))
            or 0
        )
        items = list(
            (
                await self.session.scalars(
                    select(SavedTopic)
                    .where(*filters)
                    .order_by(SavedTopic.priority.desc(), SavedTopic.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return items, total

    async def get(self, workspace_id: UUID, topic_id: UUID) -> SavedTopic | None:
        return cast(
            SavedTopic | None,
            await self.session.scalar(
                select(SavedTopic).where(
                    SavedTopic.workspace_id == workspace_id, SavedTopic.id == topic_id
                )
            ),
        )

    async def by_source(
        self, workspace_id: UUID, source_type: str, source_id: UUID
    ) -> SavedTopic | None:
        return cast(
            SavedTopic | None,
            await self.session.scalar(
                select(SavedTopic).where(
                    SavedTopic.workspace_id == workspace_id,
                    SavedTopic.source_type == source_type,
                    SavedTopic.source_id == source_id,
                )
            ),
        )
