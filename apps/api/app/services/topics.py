from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitoring import ContentItem
from app.models.news import Article, TopicEvent
from app.models.operations import AuditEntry
from app.models.topics import SavedTopic
from app.repositories.topics import TopicRepository
from app.schemas.topics import TopicBatchCreate, TopicCreate, TopicPage, TopicRead, TopicUpdate


class TopicService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TopicRepository(session)

    async def list_topics(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
        source_type: str | None,
        query: str | None,
    ) -> TopicPage:
        items, total = await self.repo.list(
            workspace_id,
            page=page,
            page_size=page_size,
            status=status,
            source_type=source_type,
            query=query,
        )
        return TopicPage(
            items=[TopicRead.model_validate(item) for item in items],
            page=page,
            page_size=page_size,
            total=total,
        )

    async def create(self, workspace_id: UUID, actor_id: UUID, payload: TopicCreate) -> TopicRead:
        title, summary, metadata = await self._source_snapshot(
            workspace_id, payload.source_type, payload.source_id
        )
        if payload.source_id:
            existing = await self.repo.by_source(
                workspace_id, payload.source_type, payload.source_id
            )
            if existing:
                return TopicRead.model_validate(existing)
        topic = SavedTopic(
            id=uuid4(),
            workspace_id=workspace_id,
            created_by=actor_id,
            title=payload.title or title,
            summary=payload.summary if payload.summary is not None else summary,
            source_type=payload.source_type,
            source_id=payload.source_id,
            status="inbox",
            priority=payload.priority,
            notes=payload.notes,
            metadata_json={**metadata, **payload.metadata},
        )
        self.session.add(topic)
        self._audit(
            workspace_id,
            actor_id,
            "topic.created",
            topic.id,
            {
                "source_type": payload.source_type,
                "source_id": str(payload.source_id) if payload.source_id else None,
            },
        )
        await self.session.commit()
        await self.session.refresh(topic)
        return TopicRead.model_validate(topic)

    async def batch(
        self, workspace_id: UUID, actor_id: UUID, payload: TopicBatchCreate
    ) -> list[TopicRead]:
        unique_ids = [*dict.fromkeys(payload.source_ids)]
        results: list[TopicRead] = []
        for source_id in unique_ids:
            results.append(
                await self.create(
                    workspace_id,
                    actor_id,
                    TopicCreate(source_type=payload.source_type, source_id=source_id),
                )
            )
        return results

    async def update(
        self, workspace_id: UUID, topic_id: UUID, actor_id: UUID, payload: TopicUpdate
    ) -> TopicRead:
        topic = await self._topic(workspace_id, topic_id)
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(topic, key, value)
        self._audit(workspace_id, actor_id, "topic.updated", topic.id, changes)
        await self.session.commit()
        await self.session.refresh(topic)
        return TopicRead.model_validate(topic)

    async def delete(self, workspace_id: UUID, topic_id: UUID, actor_id: UUID) -> None:
        topic = await self._topic(workspace_id, topic_id)
        self._audit(workspace_id, actor_id, "topic.deleted", topic.id)
        await self.session.delete(topic)
        await self.session.commit()

    async def _topic(self, workspace_id: UUID, topic_id: UUID) -> SavedTopic:
        topic = await self.repo.get(workspace_id, topic_id)
        if topic is None:
            raise HTTPException(
                status_code=404, detail={"code": "topic_not_found", "detail": "选题不存在"}
            )
        return topic

    async def _source_snapshot(
        self, workspace_id: UUID, source_type: str, source_id: UUID | None
    ) -> tuple[str, str | None, dict[str, str]]:
        if source_type == "manual":
            return "", None, {"source_kind": "imported"}
        entity: ContentItem | Article | TopicEvent | None
        if source_type == "content":
            entity = await self.session.scalar(
                select(ContentItem).where(
                    ContentItem.workspace_id == workspace_id,
                    ContentItem.id == source_id,
                )
            )
        elif source_type == "article":
            entity = await self.session.scalar(
                select(Article).where(
                    Article.workspace_id == workspace_id,
                    Article.id == source_id,
                )
            )
        else:
            entity = await self.session.scalar(
                select(TopicEvent).where(
                    TopicEvent.workspace_id == workspace_id,
                    TopicEvent.id == source_id,
                )
            )
        if entity is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "topic_source_not_found",
                    "detail": "选题来源不存在或不属于当前工作区",
                },
            )
        if source_type == "event":
            source_metadata = {
                "source_kind": "aggregated",
                "provider": "news_event",
            }
        else:
            provider = getattr(entity, "source_provider", source_type)
            source_metadata = {
                "source_kind": str(getattr(entity, "source_kind", "live")),
                "provider": str(provider),
            }
        return (
            str(entity.title),
            getattr(entity, "summary", None) or getattr(entity, "description", None),
            source_metadata,
        )

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, object] | None = None,
    ) -> None:
        digest = (
            hashlib.sha256(json.dumps(changes, default=str, sort_keys=True).encode()).hexdigest()
            if changes
            else None
        )
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="saved_topic",
                resource_id=resource_id,
                before_hash=None,
                after_hash=digest,
                change_summary_json=changes or {},
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
