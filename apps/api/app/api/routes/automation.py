from datetime import datetime
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
from app.schemas.automation import (
    AutomationActionCreate,
    AutomationActionRead,
    AutomationEvaluateRequest,
    AutomationEvaluationPage,
    AutomationEvaluationRead,
    AutomationRuleCreate,
    AutomationRuleDetail,
    AutomationRulePage,
    AutomationRuleUpdate,
    ConditionValidateRequest,
    ConditionValidateResult,
    NotificationChannelCreate,
    NotificationChannelRead,
    NotificationChannelUpdate,
    NotificationDeliveryPage,
    NotificationDeliveryRead,
    NotificationProviderRead,
    NotificationTestRequest,
)
from app.schemas.settings import ConfigFieldDescriptor
from app.services.automation import AutomationError, AutomationService

router = APIRouter(tags=["automation"])
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=200)]


async def automation_exception_handler(request: Request, exc: Exception) -> Response:
    if not isinstance(exc, AutomationError):
        raise exc
    return problem_response(
        request, status=exc.status_code, code=exc.code, title="自动化请求失败", detail=str(exc)
    )


def service(request: Request, db: DatabaseSession) -> AutomationService:
    return AutomationService(
        db,
        request.app.state.settings,
        request.app.state.notification_providers,
        request.app.state.llm_providers,
    )


@router.get("/automations", response_model=AutomationRulePage)
async def list_rules(
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    entity_type: Literal["content", "account", "news", "topic_event"] | None = None,
    enabled: bool | None = None,
) -> AutomationRulePage:
    return await service(request, db).list_rules(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        entity_type=entity_type,
        enabled=enabled,
    )


@router.post("/automations", response_model=AutomationRuleDetail, status_code=201)
async def create_rule(
    payload: AutomationRuleCreate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AutomationRuleDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).create_rule(workspace.workspace_id, auth.user.id, payload)


@router.post("/automations/validate", response_model=ConditionValidateResult)
async def validate_conditions(
    payload: ConditionValidateRequest,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> ConditionValidateResult:
    del workspace, auth
    return service(request, db).validate_conditions(payload)


@router.post("/automations/evaluate", response_model=list[AutomationEvaluationRead])
async def evaluate_rules(
    payload: AutomationEvaluateRequest,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> list[AutomationEvaluationRead]:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).evaluate(workspace.workspace_id, auth.user.id, payload)


@router.get("/automations/{rule_id}", response_model=AutomationRuleDetail)
async def get_rule(
    rule_id: UUID, request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> AutomationRuleDetail:
    return await service(request, db).get_rule(workspace.workspace_id, rule_id)


@router.patch("/automations/{rule_id}", response_model=AutomationRuleDetail)
async def update_rule(
    rule_id: UUID,
    payload: AutomationRuleUpdate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AutomationRuleDetail:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).update_rule(
        workspace.workspace_id, rule_id, auth.user.id, payload
    )


@router.delete("/automations/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    require_workspace_role(workspace, {"owner", "admin"})
    await service(request, db).delete_rule(workspace.workspace_id, rule_id, auth.user.id)
    return Response(status_code=204)


@router.post("/automations/{rule_id}/actions", response_model=AutomationActionRead, status_code=201)
async def add_action(
    rule_id: UUID,
    payload: AutomationActionCreate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> AutomationActionRead:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    return await service(request, db).add_action(
        workspace.workspace_id, rule_id, auth.user.id, payload
    )


@router.delete("/automations/{rule_id}/actions/{action_id}", status_code=204)
async def delete_action(
    rule_id: UUID,
    action_id: UUID,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    require_workspace_role(workspace, {"owner", "admin", "editor"})
    await service(request, db).delete_action(
        workspace.workspace_id, rule_id, action_id, auth.user.id
    )
    return Response(status_code=204)


@router.get("/automation-evaluations", response_model=AutomationEvaluationPage)
async def list_evaluations(
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    rule_id: UUID | None = None,
    matched: bool | None = None,
    evaluated_from: datetime | None = None,
) -> AutomationEvaluationPage:
    return await service(request, db).list_evaluations(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        rule_id=rule_id,
        matched=matched,
        evaluated_from=evaluated_from,
    )


@router.get("/notification-providers", response_model=list[NotificationProviderRead])
async def list_notification_providers(
    request: Request, workspace: CurrentWorkspace
) -> list[NotificationProviderRead]:
    del workspace
    return [
        NotificationProviderRead(
            key=provider.key,
            name=provider.name,
            is_mock=provider.is_mock,
            config_fields=[
                ConfigFieldDescriptor(
                    key=field.key,
                    label=field.label,
                    value_type=field.value_type,
                    required=field.required,
                    secret=field.secret,
                    default=field.default,
                    minimum=field.minimum,
                    maximum=field.maximum,
                    step=field.step,
                    options=[{"value": value, "label": label} for value, label in field.options],
                    placeholder=field.placeholder,
                    help_text=field.help_text,
                )
                for field in provider.config_fields
            ],
        )
        for provider in request.app.state.notification_providers.values()
    ]


@router.get("/notification-channels", response_model=list[NotificationChannelRead])
async def list_channels(
    request: Request, workspace: CurrentWorkspace, db: DatabaseSession
) -> list[NotificationChannelRead]:
    return await service(request, db).list_channels(workspace.workspace_id)


@router.post("/notification-channels", response_model=NotificationChannelRead, status_code=201)
async def create_channel(
    payload: NotificationChannelCreate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationChannelRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).create_channel(workspace.workspace_id, auth.user.id, payload)


@router.patch("/notification-channels/{channel_id}", response_model=NotificationChannelRead)
async def update_channel(
    channel_id: UUID,
    payload: NotificationChannelUpdate,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationChannelRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).update_channel(
        workspace.workspace_id, channel_id, auth.user.id, payload
    )


@router.delete("/notification-channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: UUID,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> Response:
    require_workspace_role(workspace, {"owner", "admin"})
    await service(request, db).delete_channel(workspace.workspace_id, channel_id, auth.user.id)
    return Response(status_code=204)


@router.post("/notification-channels/{channel_id}/test", response_model=NotificationDeliveryRead)
async def test_channel(
    channel_id: UUID,
    payload: NotificationTestRequest,
    request: Request,
    workspace: CurrentWorkspace,
    auth: CsrfProtectedAuth,
    db: DatabaseSession,
) -> NotificationDeliveryRead:
    require_workspace_role(workspace, {"owner", "admin"})
    return await service(request, db).test_channel(workspace.workspace_id, channel_id, payload)


@router.get("/notification-deliveries", response_model=NotificationDeliveryPage)
async def list_deliveries(
    request: Request,
    workspace: CurrentWorkspace,
    db: DatabaseSession,
    page: Page = 1,
    page_size: PageSize = 20,
    status: Literal["queued", "sending", "delivered", "failed", "cancelled"] | None = None,
    channel_id: UUID | None = None,
) -> NotificationDeliveryPage:
    return await service(request, db).list_deliveries(
        workspace.workspace_id,
        page=page,
        page_size=page_size,
        status=status,
        channel_id=channel_id,
    )
