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
from app.schemas.subscription import (
    SubscriptionEvaluateRequest,
    SubscriptionEventPage,
    SubscriptionEventRead,
    SubscriptionRuleCreate,
    SubscriptionRulePage,
    SubscriptionRuleRead,
    SubscriptionRuleUpdate,
)
from app.services.subscriptions import SubscriptionError, SubscriptionService

router = APIRouter(tags=["subscriptions"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


async def subscription_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, SubscriptionError):
        raise exc
    return problem_response(
        request,
        status=exc.status_code,
        code=exc.code,
        title="订阅请求失败",
        detail=str(exc),
    )


def service(db: DatabaseSession) -> SubscriptionService:
    return SubscriptionService(db)


@router.get("/subscriptions", response_model=SubscriptionRulePage)
async def list_subscriptions(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    enabled: bool | None = None,
) -> SubscriptionRulePage:
    return await service(db).list_rules(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        enabled=enabled,
    )


@router.post("/subscriptions", response_model=SubscriptionRuleRead, status_code=201)
async def create_subscription(
    payload: SubscriptionRuleCreate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> SubscriptionRuleRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).create_rule(workspace.workspace_id, auth.user.id, payload)


@router.post("/subscriptions/evaluate", response_model=list[SubscriptionEventRead])
async def evaluate_subscriptions(
    payload: SubscriptionEvaluateRequest,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> list[SubscriptionEventRead]:
    """Evaluate an observation and enqueue matching alerts."""

    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).evaluate(workspace.workspace_id, auth.user.id, payload)


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionRuleRead)
async def get_subscription(
    subscription_id: UUID,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
) -> SubscriptionRuleRead:
    return await service(db).get_rule(workspace.workspace_id, subscription_id)


@router.patch("/subscriptions/{subscription_id}", response_model=SubscriptionRuleRead)
async def update_subscription(
    subscription_id: UUID,
    payload: SubscriptionRuleUpdate,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> SubscriptionRuleRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(db).update_rule(
        workspace.workspace_id,
        subscription_id,
        auth.user.id,
        payload,
    )


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: UUID,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    require_workspace_role(workspace, {"owner", "admin"})
    await service(db).delete_rule(workspace.workspace_id, subscription_id, auth.user.id)
    return Response(status_code=204)


@router.get("/subscription-events", response_model=SubscriptionEventPage)
async def list_subscription_events(
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 50,
    subscription_id: UUID | None = None,
) -> SubscriptionEventPage:
    return await service(db).list_events(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        subscription_id=subscription_id,
    )
