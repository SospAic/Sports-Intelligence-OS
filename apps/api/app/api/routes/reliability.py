"""Reliability, discovery and dashboard routes.

Covers outbox / dead-letter management, notification delivery attempts,
external call attempt inspection, notification template CRUD with versioning,
dashboard statistics, and cross-entity search.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select

from app.api.dependencies import (
    CsrfProtectedAuth,
    CurrentWorkspace,
    DatabaseSession,
    require_workspace_role,
)
from app.core.problems import problem_response
from app.models.automation import NotificationDeliveryAttempt
from app.models.operations import ExternalCallAttempt
from app.schemas.reliability import (
    DashboardStatsRead,
    DeadLetterPage,
    DeadLetterRead,
    ExternalCallAttemptPage,
    ExternalCallAttemptRead,
    NotificationDeliveryAttemptRead,
    NotificationTemplateCreate,
    NotificationTemplateDetailRead,
    NotificationTemplatePage,
    NotificationTemplateRead,
    NotificationTemplateUpdate,
    NotificationTemplateVersionRead,
    OutboxEventAttemptRead,
    RollbackRequest,
    SearchPage,
)
from app.services.dashboard_stats import DashboardStatsService
from app.services.notification_template import (
    NotificationTemplateError,
    NotificationTemplateService,
)
from app.services.outbox import OutboxError, OutboxService
from app.services.search import SearchService

router = APIRouter(tags=["reliability"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


# ---------------------------------------------------------------------------
# Exception handlers (registered in main.py)
# ---------------------------------------------------------------------------


async def outbox_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, OutboxError):
        raise exc
    return problem_response(
        request, status=exc.status_code, code=exc.code, title="Outbox 请求失败", detail=str(exc)
    )


async def notification_template_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, NotificationTemplateError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="通知模板请求失败",
        detail=str(exc),
    )


# ===================================================================
# Outbox / Dead Letter routes
# ===================================================================


@router.get("/outbox/dead-letters", response_model=DeadLetterPage)
async def list_dead_letters(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
) -> DeadLetterPage:
    """Return a paginated list of dead-letter events for the current workspace."""
    items, total = await OutboxService(db).list_dead_letters(
        workspace.workspace_id, page=page, page_size=page_size
    )
    return DeadLetterPage(
        items=[DeadLetterRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/outbox/dead-letters/{dead_letter_id}/replay", status_code=200)
async def replay_dead_letter(
    dead_letter_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Replay a dead-lettered event by resetting it to pending."""
    require_workspace_role(workspace, {"owner", "admin"})
    event = await OutboxService(db).replay_dead_letter(workspace.workspace_id, dead_letter_id)
    return {
        "ok": True,
        "outbox_event_id": str(event.id),
        "publish_status": event.publish_status,
    }


@router.post("/outbox/dead-letters/{dead_letter_id}/discard", status_code=200)
async def discard_dead_letter(
    dead_letter_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> dict[str, Any]:
    """Permanently discard a dead-letter event."""
    require_workspace_role(workspace, {"owner", "admin"})
    dead_letter = await OutboxService(db).discard_dead_letter(
        workspace.workspace_id, dead_letter_id
    )
    return {
        "ok": True,
        "dead_letter_id": str(dead_letter.id),
        "replay_status": dead_letter.replay_status,
    }


@router.get(
    "/outbox/events/{event_id}/attempts",
    response_model=list[OutboxEventAttemptRead],
)
async def list_outbox_event_attempts(
    event_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[OutboxEventAttemptRead]:
    """List all delivery attempts for a given outbox event, oldest first."""
    attempts = await OutboxService(db).list_attempts(workspace.workspace_id, event_id)
    return [OutboxEventAttemptRead.model_validate(a) for a in attempts]


# ===================================================================
# Notification delivery attempt routes
# ===================================================================


@router.get(
    "/notification-deliveries/{delivery_id}/attempts",
    response_model=list[NotificationDeliveryAttemptRead],
)
async def list_delivery_attempts(
    delivery_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[NotificationDeliveryAttemptRead]:
    """List all attempts for a notification delivery, oldest first."""
    items = (
        await db.scalars(
            select(NotificationDeliveryAttempt)
            .where(
                NotificationDeliveryAttempt.delivery_id == delivery_id,
                NotificationDeliveryAttempt.workspace_id == workspace.workspace_id,
            )
            .order_by(NotificationDeliveryAttempt.attempt_number)
        )
    ).all()
    return [NotificationDeliveryAttemptRead.model_validate(a) for a in items]


# ===================================================================
# External call attempt routes
# ===================================================================


@router.get("/external-call-attempts", response_model=ExternalCallAttemptPage)
async def list_external_call_attempts(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    provider_key: str | None = None,
    call_type: str | None = None,
    status: str | None = None,
) -> ExternalCallAttemptPage:
    """List external call attempts with optional filters."""
    filters = [ExternalCallAttempt.workspace_id == workspace.workspace_id]
    if provider_key is not None:
        filters.append(ExternalCallAttempt.provider_key == provider_key)
    if call_type is not None:
        filters.append(ExternalCallAttempt.call_type == call_type)
    if status is not None:
        filters.append(ExternalCallAttempt.status == status)

    total = int(
        await db.scalar(select(func.count()).select_from(ExternalCallAttempt).where(*filters)) or 0
    )
    items = (
        await db.scalars(
            select(ExternalCallAttempt)
            .where(*filters)
            .order_by(ExternalCallAttempt.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    return ExternalCallAttemptPage(
        items=[ExternalCallAttemptRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


# ===================================================================
# Notification template routes
# ===================================================================


def _template_service(db: DatabaseSession) -> NotificationTemplateService:
    return NotificationTemplateService(db)


@router.get("/notification-templates", response_model=NotificationTemplatePage)
async def list_notification_templates(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    category: str | None = None,
) -> NotificationTemplatePage:
    """Return a paginated list of notification templates."""
    result = await _template_service(db).list_templates(
        workspace.workspace_id, page=page, page_size=page_size, category=category
    )
    return NotificationTemplatePage(
        items=[NotificationTemplateRead.model_validate(item) for item in result["items"]],
        page=result["page"],
        page_size=result["page_size"],
        total=result["total"],
    )


@router.post(
    "/notification-templates",
    response_model=NotificationTemplateDetailRead,
    status_code=201,
)
async def create_notification_template(
    payload: NotificationTemplateCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationTemplateDetailRead:
    """Create a new notification template with its initial draft version."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    result = await _template_service(db).create_template(
        workspace_id=workspace.workspace_id,
        actor_id=auth.user.id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        variables_schema=payload.variables_schema,
    )
    return NotificationTemplateDetailRead.model_validate(result)


@router.get(
    "/notification-templates/{template_id}",
    response_model=NotificationTemplateDetailRead,
)
async def get_notification_template(
    template_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> NotificationTemplateDetailRead:
    """Return a single template with all its versions."""
    result = await _template_service(db).get_template(workspace.workspace_id, template_id)
    return NotificationTemplateDetailRead.model_validate(result)


@router.put(
    "/notification-templates/{template_id}",
    response_model=NotificationTemplateVersionRead,
)
async def update_notification_template_draft(
    template_id: UUID,
    payload: NotificationTemplateUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationTemplateVersionRead:
    """Update the current draft version, or create a new draft if latest is published."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    result = await _template_service(db).update_draft(
        workspace_id=workspace.workspace_id,
        template_id=template_id,
        actor_id=auth.user.id,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        variables_schema=payload.variables_schema,
        change_notes=payload.change_notes,
    )
    return NotificationTemplateVersionRead.model_validate(result)


@router.post(
    "/notification-templates/{template_id}/publish",
    response_model=NotificationTemplateVersionRead,
)
async def publish_notification_template(
    template_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationTemplateVersionRead:
    """Publish the current draft version of a template."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    result = await _template_service(db).publish_version(
        workspace_id=workspace.workspace_id,
        template_id=template_id,
        actor_id=auth.user.id,
    )
    return NotificationTemplateVersionRead.model_validate(result)


@router.post(
    "/notification-templates/{template_id}/rollback",
    response_model=NotificationTemplateVersionRead,
)
async def rollback_notification_template(
    template_id: UUID,
    payload: RollbackRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationTemplateVersionRead:
    """Rollback a template by creating a new draft that copies the specified version."""
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    result = await _template_service(db).rollback_version(
        workspace_id=workspace.workspace_id,
        template_id=template_id,
        version_id=payload.version_id,
        actor_id=auth.user.id,
    )
    return NotificationTemplateVersionRead.model_validate(result)


@router.delete("/notification-templates/{template_id}", status_code=204)
async def delete_notification_template(
    template_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    """Delete a template and all its versions."""
    require_workspace_role(workspace, {"owner", "admin"})
    await _template_service(db).delete_template(workspace.workspace_id, template_id, auth.user.id)
    return Response(status_code=204)


@router.get(
    "/notification-templates/{template_id}/versions",
    response_model=list[NotificationTemplateVersionRead],
)
async def list_template_versions(
    template_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> list[NotificationTemplateVersionRead]:
    """List all versions of a template, newest first."""
    result = await _template_service(db).list_versions(workspace.workspace_id, template_id)
    return [NotificationTemplateVersionRead.model_validate(v) for v in result]


# ===================================================================
# Dashboard stats routes
# ===================================================================


@router.get("/dashboard/stats", response_model=DashboardStatsRead)
async def get_dashboard_stats(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> DashboardStatsRead:
    """Return cached dashboard statistics for the current workspace."""
    stats = await DashboardStatsService(db).get_stats(workspace.workspace_id)
    return DashboardStatsRead(stats=stats)


@router.post("/dashboard/stats/refresh", response_model=DashboardStatsRead)
async def refresh_dashboard_stats(
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> DashboardStatsRead:
    """Force recalculate all dashboard statistics."""
    require_workspace_role(workspace, {"owner", "admin"})
    stats = await DashboardStatsService(db).calculate_stats(workspace.workspace_id)
    return DashboardStatsRead(stats=stats)


# ===================================================================
# Search routes
# ===================================================================


@router.get("/search", response_model=SearchPage)
async def search(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    q: Annotated[str, Query(min_length=1, max_length=200)] = "",
    page: Page = 1,
    page_size: PageSize = 20,
    entity_types: Annotated[
        str | None,
        Query(description="Comma-separated entity types to search"),
    ] = None,
) -> SearchPage:
    """Full-text search across all entities in the workspace."""
    parsed_types: list[str] | None = None
    if entity_types:
        parsed_types = [t.strip() for t in entity_types.split(",") if t.strip()]
    return await SearchService(db).search(
        workspace_id=workspace.workspace_id,
        query=q,
        page=page,
        page_size=page_size,
        entity_types=parsed_types,
    )
