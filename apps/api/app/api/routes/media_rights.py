from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.schemas.media_rights import MediaRightsPage, MediaRightsRead, MediaRightsUpdate
from app.services.media_rights import MediaRightsError, MediaRightsService

router = APIRouter(tags=["media-rights"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


async def media_rights_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, MediaRightsError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="素材权利请求失败",
        detail=str(exc),
    )


@router.get("/storage/rights", response_model=MediaRightsPage)
async def list_media_rights(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 25,
    rights_status: Literal["unknown", "pending_review", "approved", "restricted", "expired"]
    | None = None,
) -> MediaRightsPage:
    return await MediaRightsService(db).list(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        rights_status=rights_status,
    )


@router.patch("/storage/artifacts/{artifact_id}/rights", response_model=MediaRightsRead)
async def update_media_rights(
    artifact_id: UUID,
    payload: MediaRightsUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> MediaRightsRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await MediaRightsService(db).update(
        workspace.workspace_id,
        artifact_id,
        auth.user.id,
        payload,
    )
