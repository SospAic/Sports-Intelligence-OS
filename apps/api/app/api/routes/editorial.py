from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.schemas.editorial import (
    EditorialBulkResult,
    EditorialBulkUpdate,
    EditorialItemCreate,
    EditorialItemPage,
    EditorialItemRead,
    EditorialItemUpdate,
    EditorialSavedViewCreate,
    EditorialSavedViewRead,
    EditorialSavedViewUpdate,
)
from app.services.editorial import EditorialError, EditorialService

router = APIRouter(tags=["editorial"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


async def editorial_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, EditorialError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="审核队列请求失败",
        detail=str(exc),
    )


def service(db: DatabaseSession) -> EditorialService:
    return EditorialService(db)


@router.get("/editorial-items", response_model=EditorialItemPage)
async def list_editorial_items(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
    status: str | None = None,
    assignee_id: UUID | None = None,
    overdue: bool = False,
    unassigned: bool = False,
    priority_min: int | None = Query(default=None, ge=0, le=100),
    priority_max: int | None = Query(default=None, ge=0, le=100),
) -> EditorialItemPage:
    return await service(db).list_items(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        status=status,
        assignee_id=assignee_id,
        overdue=overdue,
        unassigned=unassigned,
        priority_min=priority_min,
        priority_max=priority_max,
    )


@router.get("/editorial-views", response_model=list[EditorialSavedViewRead])
async def list_editorial_views(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[EditorialSavedViewRead]:
    return await service(db).list_views(workspace.workspace_id)


@router.post("/editorial-views", response_model=EditorialSavedViewRead, status_code=201)
async def create_editorial_view(
    payload: EditorialSavedViewCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> EditorialSavedViewRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await service(db).create_view(workspace.workspace_id, auth.user.id, payload)


@router.patch("/editorial-views/{view_id}", response_model=EditorialSavedViewRead)
async def update_editorial_view(
    view_id: UUID,
    payload: EditorialSavedViewUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> EditorialSavedViewRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    view = await service(db).get_view(workspace.workspace_id, view_id)
    if view.created_by != auth.user.id and workspace.role not in {"owner", "admin"}:
        require_workspace_role(workspace, {"owner", "admin"})
    return await service(db).update_view(workspace.workspace_id, view_id, auth.user.id, payload)


@router.delete("/editorial-views/{view_id}", status_code=204)
async def delete_editorial_view(
    view_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    view = await service(db).get_view(workspace.workspace_id, view_id)
    if view.created_by != auth.user.id:
        require_workspace_role(workspace, {"owner", "admin"})
    await service(db).delete_view(
        workspace.workspace_id,
        view_id,
        auth.user.id,
        can_manage=workspace.role in {"owner", "admin"},
    )
    return Response(status_code=204)


@router.patch("/editorial-items/bulk", response_model=EditorialBulkResult)
async def bulk_update_editorial_items(
    payload: EditorialBulkUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> EditorialBulkResult:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    if payload.status == "approved":
        require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).bulk_update(workspace.workspace_id, auth.user.id, payload)


@router.post("/editorial-items", response_model=EditorialItemRead, status_code=201)
async def create_editorial_item(
    payload: EditorialItemCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> EditorialItemRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    return await service(db).create_item(workspace.workspace_id, auth.user.id, payload)


@router.get("/editorial-items/{item_id}", response_model=EditorialItemRead)
async def get_editorial_item(
    item_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> EditorialItemRead:
    return await service(db).get_item(workspace.workspace_id, item_id)


@router.patch("/editorial-items/{item_id}", response_model=EditorialItemRead)
async def update_editorial_item(
    item_id: UUID,
    payload: EditorialItemUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> EditorialItemRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    if payload.status == "approved":
        require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).update_item(
        workspace.workspace_id,
        item_id,
        auth.user.id,
        payload,
    )
