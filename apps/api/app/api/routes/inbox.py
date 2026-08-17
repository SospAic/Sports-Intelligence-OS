from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.inbox import (
    InboxReadStateBulkUpsert,
    InboxReadStateRead,
    InboxReadStateUpsert,
)
from app.schemas.inbox_queue import (
    InboxQueueStateBulkPatch,
    InboxQueueStatePatch,
    InboxQueueStateRead,
    InboxSavedViewCreate,
    InboxSavedViewRead,
    InboxSavedViewUpdate,
)
from app.services.inbox import InboxKeyError, InboxService, InboxServiceError

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("/read-states", response_model=list[InboxReadStateRead])
async def list_read_states(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    item_key: Annotated[list[str] | None, Query()] = None,
) -> list[InboxReadStateRead]:
    try:
        return await InboxService(db).list_read_states(
            workspace.workspace_id,
            workspace.auth.user.id,
            item_key or [],
        )
    except InboxKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/read-states", response_model=InboxReadStateRead)
async def mark_read(
    payload: InboxReadStateUpsert,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> InboxReadStateRead:
    try:
        return await InboxService(db).mark_read(
            workspace.workspace_id,
            auth.user.id,
            payload.item_key,
        )
    except InboxKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/read-states/bulk", response_model=list[InboxReadStateRead])
async def mark_many_read(
    payload: InboxReadStateBulkUpsert,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> list[InboxReadStateRead]:
    try:
        return await InboxService(db).mark_many_read(
            workspace.workspace_id,
            auth.user.id,
            payload.item_keys,
        )
    except InboxKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/queue-states", response_model=list[InboxQueueStateRead])
async def list_queue_states(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    item_key: Annotated[list[str] | None, Query()] = None,
) -> list[InboxQueueStateRead]:
    try:
        return await InboxService(db).list_queue_states(workspace.workspace_id, item_key or [])
    except InboxKeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/queue-states/bulk", response_model=list[InboxQueueStateRead])
async def update_queue_states_bulk(
    payload: InboxQueueStateBulkPatch,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> list[InboxQueueStateRead]:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        return await InboxService(db).update_queue_states_bulk(
            workspace.workspace_id, auth.user.id, payload
        )
    except (InboxKeyError, InboxServiceError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 422),
            detail={"code": getattr(exc, "code", "inbox_key_invalid"), "detail": str(exc)},
        ) from exc


@router.patch("/queue-states/{item_key}", response_model=InboxQueueStateRead)
async def update_queue_state(
    item_key: str,
    payload: InboxQueueStatePatch,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> InboxQueueStateRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        return await InboxService(db).update_queue_state(
            workspace.workspace_id, auth.user.id, item_key, payload
        )
    except (InboxKeyError, InboxServiceError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 422),
            detail={"code": getattr(exc, "code", "inbox_key_invalid"), "detail": str(exc)},
        ) from exc


@router.get("/views", response_model=list[InboxSavedViewRead])
async def list_inbox_views(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[InboxSavedViewRead]:
    return await InboxService(db).list_views(workspace.workspace_id)


@router.post("/views", response_model=InboxSavedViewRead, status_code=201)
async def create_inbox_view(
    payload: InboxSavedViewCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> InboxSavedViewRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        return await InboxService(db).create_view(workspace.workspace_id, auth.user.id, payload)
    except InboxServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "detail": str(exc)}
        ) from exc


@router.patch("/views/{view_id}", response_model=InboxSavedViewRead)
async def update_inbox_view(
    view_id: UUID,
    payload: InboxSavedViewUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> InboxSavedViewRead:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = InboxService(db)
    try:
        view = await service.get_view(workspace.workspace_id, view_id)
        if view.created_by != auth.user.id and workspace.role not in {"owner", "admin"}:
            require_workspace_role(workspace, {"owner", "admin"})
        return await service.update_view(workspace.workspace_id, auth.user.id, view_id, payload)
    except InboxServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "detail": str(exc)}
        ) from exc


@router.delete("/views/{view_id}", status_code=204)
async def delete_inbox_view(
    view_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    service = InboxService(db)
    try:
        view = await service.get_view(workspace.workspace_id, view_id)
        if view.created_by != auth.user.id and workspace.role not in {"owner", "admin"}:
            require_workspace_role(workspace, {"owner", "admin"})
        await service.delete_view(workspace.workspace_id, auth.user.id, view_id)
    except InboxServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "detail": str(exc)}
        ) from exc
    return Response(status_code=204)
