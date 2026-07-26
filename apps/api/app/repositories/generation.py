from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.generation import (
    GenerationRun,
    GenerationWorkflow,
    PromptCollection,
    PromptVersion,
)


class GenerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def prompt_collection(
        self, workspace_id: UUID, collection_id: UUID
    ) -> PromptCollection | None:
        return cast(
            PromptCollection | None,
            await self.session.scalar(
                select(PromptCollection).where(
                    PromptCollection.workspace_id == workspace_id,
                    PromptCollection.id == collection_id,
                )
            ),
        )

    async def prompt_collection_by_key(
        self, workspace_id: UUID, key: str
    ) -> PromptCollection | None:
        return cast(
            PromptCollection | None,
            await self.session.scalar(
                select(PromptCollection).where(
                    PromptCollection.workspace_id == workspace_id, PromptCollection.key == key
                )
            ),
        )

    async def list_prompt_collections(
        self, workspace_id: UUID, page: int, page_size: int
    ) -> tuple[list[PromptCollection], int]:
        items = list(
            (
                await self.session.scalars(
                    select(PromptCollection)
                    .where(PromptCollection.workspace_id == workspace_id)
                    .order_by(PromptCollection.updated_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (
                await self.session.scalar(
                    select(func.count())
                    .select_from(PromptCollection)
                    .where(PromptCollection.workspace_id == workspace_id)
                )
            )
            or 0
        )
        return items, total

    async def prompt_versions(self, workspace_id: UUID, collection_id: UUID) -> list[PromptVersion]:
        return list(
            (
                await self.session.scalars(
                    select(PromptVersion)
                    .where(
                        PromptVersion.workspace_id == workspace_id,
                        PromptVersion.collection_id == collection_id,
                    )
                    .order_by(PromptVersion.created_at.desc())
                )
            ).all()
        )

    async def prompt_version(self, workspace_id: UUID, version_id: UUID) -> PromptVersion | None:
        return cast(
            PromptVersion | None,
            await self.session.scalar(
                select(PromptVersion).where(
                    PromptVersion.workspace_id == workspace_id, PromptVersion.id == version_id
                )
            ),
        )

    async def prompt_version_by_label(
        self, workspace_id: UUID, collection_id: UUID, version: str
    ) -> PromptVersion | None:
        return cast(
            PromptVersion | None,
            await self.session.scalar(
                select(PromptVersion).where(
                    PromptVersion.workspace_id == workspace_id,
                    PromptVersion.collection_id == collection_id,
                    PromptVersion.version == version,
                )
            ),
        )

    async def workflow(self, workspace_id: UUID, workflow_id: UUID) -> GenerationWorkflow | None:
        return cast(
            GenerationWorkflow | None,
            await self.session.scalar(
                select(GenerationWorkflow).where(
                    GenerationWorkflow.workspace_id == workspace_id,
                    GenerationWorkflow.id == workflow_id,
                )
            ),
        )

    async def workflow_by_key(self, workspace_id: UUID, key: str) -> GenerationWorkflow | None:
        return cast(
            GenerationWorkflow | None,
            await self.session.scalar(
                select(GenerationWorkflow).where(
                    GenerationWorkflow.workspace_id == workspace_id,
                    GenerationWorkflow.key == key,
                )
            ),
        )

    async def workflows(self, workspace_id: UUID) -> list[GenerationWorkflow]:
        return list(
            (
                await self.session.scalars(
                    select(GenerationWorkflow)
                    .where(GenerationWorkflow.workspace_id == workspace_id)
                    .order_by(GenerationWorkflow.name)
                )
            ).all()
        )

    async def run(self, workspace_id: UUID, run_id: UUID) -> GenerationRun | None:
        return cast(
            GenerationRun | None,
            await self.session.scalar(
                select(GenerationRun)
                .options(selectinload(GenerationRun.steps))
                .where(GenerationRun.workspace_id == workspace_id, GenerationRun.id == run_id)
            ),
        )

    async def run_by_idempotency(
        self, workspace_id: UUID, idempotency_key: str
    ) -> GenerationRun | None:
        return cast(
            GenerationRun | None,
            await self.session.scalar(
                select(GenerationRun)
                .options(selectinload(GenerationRun.steps))
                .where(
                    GenerationRun.workspace_id == workspace_id,
                    GenerationRun.idempotency_key == idempotency_key,
                )
            ),
        )

    async def list_runs(
        self,
        workspace_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None,
    ) -> tuple[list[GenerationRun], int]:
        conditions = [GenerationRun.workspace_id == workspace_id]
        if status:
            conditions.append(GenerationRun.status == status)
        items = list(
            (
                await self.session.scalars(
                    select(GenerationRun)
                    .options(selectinload(GenerationRun.steps))
                    .where(*conditions)
                    .order_by(GenerationRun.created_at.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        total = int(
            (
                await self.session.scalar(
                    select(func.count()).select_from(GenerationRun).where(*conditions)
                )
            )
            or 0
        )
        return items, total
