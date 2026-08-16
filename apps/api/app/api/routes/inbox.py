from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import CsrfProtectedAuth, CurrentWorkspace, DatabaseSession
from app.schemas.inbox import (
    InboxReadStateBulkUpsert,
    InboxReadStateRead,
    InboxReadStateUpsert,
)
from app.services.inbox import InboxKeyError, InboxService

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
