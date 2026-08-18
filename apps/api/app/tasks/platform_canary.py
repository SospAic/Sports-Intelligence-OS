"""Scheduled official-platform API synthetic monitoring.

This task deliberately probes only configured official API credentials. Public
pages and authorized browser sessions have different consent, rate-limit and
session-lifetime semantics, so they remain operator-triggered through the
readiness endpoint. Results reuse the external-call audit trail and system
events instead of introducing another state table or a fake notification.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.platforms.base import PlatformAdapter
from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import get_settings
from app.db.session import create_engine_and_session
from app.models.monitoring import Platform
from app.models.operations import ExternalCallAttempt, SystemEvent
from app.models.workspace import Workspace
from app.providers.registry import ProviderRegistry
from app.services.error_detail import business_hint_for
from app.services.platform_canary import run_platform_canary
from app.services.platform_credentials import PlatformCredentialService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_UNHEALTHY_STATUSES = frozenset({"failed", "degraded", "blocked"})
_EVENT_TYPE = "platform.canary_failed"


def should_run_canary(
    last_checked_at: datetime | None,
    *,
    now: datetime,
    interval_seconds: int,
) -> bool:
    """Return whether the scheduler should issue another probe.

    The explicit timestamp comparison makes the scheduler idempotent when Beat
    is restarted or a task is delivered twice. Future timestamps are treated as
    recent rather than causing a tight retry loop after clock skew.
    """

    if last_checked_at is None:
        return True
    checked = last_checked_at
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    else:
        checked = checked.astimezone(UTC)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    return current - checked >= timedelta(seconds=interval_seconds)


def canary_status_from_attempt(attempt: ExternalCallAttempt | None) -> str | None:
    """Map the persisted external-call row back to the readiness status."""

    if attempt is None:
        return None
    if attempt.error_code in {
        "platform_credentials_not_configured",
        "platform_adapter_not_registered",
    }:
        return "blocked"
    if attempt.status == "success":
        summary = attempt.response_summary or {}
        return "degraded" if summary.get("health_status") == "degraded" else "passed"
    return "failed"


def is_unhealthy_canary_status(status: str | None) -> bool:
    return status in _UNHEALTHY_STATUSES


async def _latest_probe(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    platform: Platform,
) -> ExternalCallAttempt | None:
    """Find the last probe for a platform without relying on JSON SQL syntax."""

    provider_keys = {platform.key, platform.adapter_key}
    attempts = list(
        (
            await session.scalars(
                select(ExternalCallAttempt)
                .where(
                    ExternalCallAttempt.workspace_id == workspace_id,
                    ExternalCallAttempt.call_type == "platform_api",
                    ExternalCallAttempt.entity_type == "platform_canary",
                    ExternalCallAttempt.provider_key.in_(provider_keys),
                )
                .order_by(desc(ExternalCallAttempt.started_at))
                .limit(100)
            )
        ).all()
    )
    for attempt in attempts:
        summary = attempt.request_summary or {}
        if isinstance(summary, dict) and summary.get("platform_key") == platform.key:
            return attempt
    return None


async def _update_failure_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    platform: Platform,
    current_status: str,
    previous_status: str | None,
    checked_at: datetime,
    detail: str,
    error_code: str | None,
    credential_source: str,
) -> str | None:
    """Create one open event on transition and resolve it on recovery."""

    event = await session.scalar(
        select(SystemEvent)
        .where(
            SystemEvent.workspace_id == workspace_id,
            SystemEvent.event_type == _EVENT_TYPE,
            SystemEvent.resource_type == "platform",
            SystemEvent.resource_id == platform.id,
            SystemEvent.status == "open",
        )
        .order_by(desc(SystemEvent.created_at))
    )
    if is_unhealthy_canary_status(current_status):
        if event is not None or is_unhealthy_canary_status(previous_status):
            return None
        severity = "error" if current_status == "failed" else "warning"
        session.add(
            SystemEvent(
                id=uuid4(),
                workspace_id=workspace_id,
                severity=severity,
                category="platform_canary",
                event_type=_EVENT_TYPE,
                message=f"平台「{platform.name}」官方 API 探针异常",
                resource_type="platform",
                resource_id=platform.id,
                status="open",
                metadata_safe_json={
                    "platform_key": platform.key,
                    "adapter_key": platform.adapter_key,
                    "canary_status": current_status,
                    "credential_source": credential_source,
                    "checked_at": checked_at.isoformat(),
                },
                trace_id=uuid4(),
                created_at=checked_at,
                error_code=error_code,
                error_detail=detail[:2000],
                error_hint=business_hint_for(error_code, category="external_call")
                if error_code
                else detail[:500],
            )
        )
        await session.commit()
        return "escalated"

    if current_status == "passed" and event is not None:
        metadata = dict(event.metadata_safe_json or {})
        metadata.update(
            {
                "resolved_at": checked_at.isoformat(),
                "recovery_status": current_status,
            }
        )
        event.status = "resolved"
        event.metadata_safe_json = metadata
        event.error_detail = None
        event.error_hint = "平台官方 API 探针已恢复。"
        await session.commit()
        return "resolved"
    return None


async def _close_registry(registry: ProviderRegistry[PlatformAdapter]) -> None:
    for adapter in registry.values():
        await adapter.aclose()


async def _run_scheduled_platform_canaries() -> dict[str, int]:
    settings = get_settings()
    result = {
        "enabled": int(settings.platform_canary_enabled),
        "workspaces": 0,
        "checked": 0,
        "skipped": 0,
        "passed": 0,
        "degraded": 0,
        "failed": 0,
        "blocked": 0,
        "escalated": 0,
        "resolved": 0,
        "errors": 0,
    }
    if not settings.platform_canary_enabled:
        return result

    engine, session_factory = create_engine_and_session(settings)
    registry = build_platform_adapter_registry(settings)
    now = datetime.now(UTC)
    try:
        async with session_factory() as session:
            workspace_ids = list(
                (
                    await session.scalars(
                        select(Workspace.id).where(Workspace.status == "active")
                    )
                ).all()
            )
            platforms = list(
                (
                    await session.scalars(
                        select(Platform)
                        .where(Platform.enabled.is_(True))
                        .order_by(Platform.name)
                    )
                ).all()
            )
            for workspace_id in workspace_ids:
                result["workspaces"] += 1
                credential_service = PlatformCredentialService(session, settings)
                for platform in platforms:
                    credential = await credential_service.get(workspace_id, platform.key)
                    # Synthetic monitoring must never create browser sessions or
                    # silently turn a public-page policy into an API call.
                    if credential.mode != "api" or not credential.configured:
                        result["skipped"] += 1
                        continue

                    latest = await _latest_probe(
                        session, workspace_id=workspace_id, platform=platform
                    )
                    if not should_run_canary(
                        latest.started_at if latest is not None else None,
                        now=now,
                        interval_seconds=settings.platform_canary_interval_seconds,
                    ):
                        result["skipped"] += 1
                        continue

                    previous_status = canary_status_from_attempt(latest)
                    try:
                        probe = await run_platform_canary(
                            session=session,
                            settings=settings,
                            registry=registry,
                            workspace_id=workspace_id,
                            actor_id=None,
                            platform_key=platform.key,
                        )
                        current_status = str(probe.status)
                        result["checked"] += 1
                        result[current_status] = result.get(current_status, 0) + 1
                        transition = await _update_failure_event(
                            session,
                            workspace_id=workspace_id,
                            platform=platform,
                            current_status=current_status,
                            previous_status=previous_status,
                            checked_at=probe.checked_at,
                            detail=probe.detail,
                            error_code=probe.error_code,
                            credential_source=probe.credential_source,
                        )
                        if transition is not None:
                            result[transition] += 1
                    except Exception:  # noqa: BLE001 - one platform must not stop the sweep
                        await session.rollback()
                        result["errors"] += 1
                        logger.exception(
                            "scheduled_platform_canary_failed",
                            extra={
                                "workspace_id": str(workspace_id),
                                "platform_key": platform.key,
                            },
                        )
    finally:
        await _close_registry(registry)
        await engine.dispose()
    return result


@celery_app.task(name="app.tasks.platform_canary.run_scheduled_platform_canaries")  # type: ignore[untyped-decorator]
def run_scheduled_platform_canaries() -> dict[str, int]:
    return asyncio.run(_run_scheduled_platform_canaries())
