from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.schemas.monitoring import SyncRunRead
from app.schemas.operations import (
    AuditEntryPage,
    OperationTaskPage,
    SystemEventPage,
)
from app.services.operations import OperationsService, UnsupportedTaskCancelError

router = APIRouter(prefix="/operations", tags=["operations"])


class CancelTaskRequest(BaseModel):
    category: str


@router.post("/tasks/{task_id}/cancel", response_model=SyncRunRead)
async def cancel_task(
    task_id: UUID,
    payload: CancelTaskRequest,
    workspace: CurrentWorkspace,
    _: CsrfProtectedAuth,
    db: DatabaseSession,
) -> SyncRunRead:
    """Terminate a background task shown on the operations dashboard.

    Only ``platform_sync`` tasks are cancellable today; other categories raise a
    501 so the UI can disable the action instead of faking support.
    """
    require_workspace_role(workspace, {"owner", "admin", "editor", "analyst"})
    try:
        return await OperationsService(db).cancel_task(
            workspace.workspace_id, task_id, payload.category
        )
    except UnsupportedTaskCancelError as exc:
        raise HTTPException(
            status_code=501,
            detail={"code": "unsupported_task_cancel", "detail": str(exc)},
        ) from None


Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


@router.get("/tasks", response_model=OperationTaskPage)
async def list_tasks(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    category: str | None = None,
    status: str | None = None,
) -> OperationTaskPage:
    return await OperationsService(db).tasks(
        workspace.workspace_id, page=page, page_size=page_size, category=category, status=status
    )


@router.get("/events", response_model=SystemEventPage)
async def list_events(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    severity: str | None = None,
    category: str | None = None,
) -> SystemEventPage:
    return await OperationsService(db).events(
        workspace.workspace_id, page=page, page_size=page_size, severity=severity, category=category
    )


@router.get("/audits", response_model=AuditEntryPage)
async def list_audits(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    action: str | None = None,
    resource_type: str | None = None,
) -> AuditEntryPage:
    return await OperationsService(db).audits(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        action=action,
        resource_type=resource_type,
    )
