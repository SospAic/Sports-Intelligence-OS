from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.topics import TopicBatchCreate, TopicCreate, TopicPage, TopicRead, TopicUpdate
from app.services.topics import TopicService

router = APIRouter(prefix="/topics", tags=["topics"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=TopicPage)
async def list_topics(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    status: Literal["inbox", "planned", "in_progress", "completed", "archived"] | None = None,
    source_type: Literal["content", "article", "event", "manual"] | None = None,
    query: str | None = None,
) -> TopicPage:
    return await TopicService(db).list_topics(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        status=status,
        source_type=source_type,
        query=query,
    )


@router.post("", response_model=TopicRead, status_code=201)
async def create_topic(
    payload: TopicCreate, workspace: CurrentWorkspace, auth: CsrfProtectedAuth, db: DatabaseSession
) -> TopicRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await TopicService(db).create(workspace.workspace_id, auth.user.id, payload)


@router.post("/batch", response_model=list[TopicRead], status_code=201)
async def batch_topics(
    payload: TopicBatchCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> list[TopicRead]:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await TopicService(db).batch(workspace.workspace_id, auth.user.id, payload)


@router.patch("/{topic_id}", response_model=TopicRead)
async def update_topic(
    topic_id: UUID,
    payload: TopicUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> TopicRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await TopicService(db).update(workspace.workspace_id, topic_id, auth.user.id, payload)


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: UUID, workspace: CurrentWorkspace, auth: CsrfProtectedAuth, db: DatabaseSession
) -> Response:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    await TopicService(db).delete(workspace.workspace_id, topic_id, auth.user.id)
    return Response(status_code=204)
