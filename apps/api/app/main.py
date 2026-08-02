import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.api.router import api_router
from app.api.routes.automation import automation_exception_handler
from app.api.routes.editorial_rules import editorial_rule_exception_handler
from app.api.routes.generation import generation_exception_handler
from app.api.routes.health import router as health_router
from app.api.routes.monitoring import monitoring_exception_handler, sync_exception_handler
from app.api.routes.news import news_exception_handler
from app.api.routes.reliability import (
    notification_template_exception_handler,
    outbox_exception_handler,
)
from app.api.routes.settings import settings_exception_handler
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.problems import http_exception_handler, validation_exception_handler
from app.db.session import create_engine_and_session
from app.providers.llm.registry import build_llm_provider_registry
from app.providers.news.registry import build_news_provider_registry
from app.providers.notifications.registry import build_notification_provider_registry
from app.services.automation import AutomationError
from app.services.editorial_rules import EditorialRuleError
from app.services.generation import GenerationError
from app.services.monitoring import MonitoringError
from app.services.news import NewsError
from app.services.notification_template import NotificationTemplateError
from app.services.outbox import OutboxError
from app.services.platform_catalog_seed import seed_platform_catalog
from app.services.platform_credentials import PlatformCredentialError
from app.services.settings import SettingsError
from app.services.sync import SyncError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine, session_factory = create_engine_and_session(resolved_settings)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.redis = Redis.from_url(
            resolved_settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=resolved_settings.redis_connect_timeout_seconds,
            socket_timeout=resolved_settings.redis_socket_timeout_seconds,
            max_connections=resolved_settings.redis_max_connections,
            health_check_interval=resolved_settings.redis_health_check_interval_seconds,
            retry_on_timeout=resolved_settings.redis_retry_on_timeout,
        )
        app.state.platform_adapters = build_platform_adapter_registry(resolved_settings)
        app.state.news_providers = build_news_provider_registry(resolved_settings)
        app.state.llm_providers = build_llm_provider_registry(resolved_settings)
        app.state.notification_providers = build_notification_provider_registry(resolved_settings)
        # Idempotently sync the platform catalog (incl. each platform's default
        # adapter key) with the code. This is what flips YouTube / TikTok / Douyin
        # to the yt-dlp adapter on deploy without a manual CLI step.
        try:
            async with session_factory() as seed_session:
                created, updated = await seed_platform_catalog(seed_session)
                if updated:
                    logger.info("platform catalog synced on startup: %s updated", updated)
        except Exception:  # noqa: BLE001 - never block boot on a catalog sync
            logger.exception("platform catalog seed failed during startup")
        try:
            yield
        finally:
            for adapter in app.state.platform_adapters.values():
                close = getattr(adapter, "aclose", None)
                if close is not None:
                    await close()
            for provider in app.state.news_providers.values():
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
            for provider in app.state.llm_providers.values():
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
            for provider in app.state.notification_providers.values():
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
            await app.state.redis.aclose()
            await engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        docs_url="/docs" if resolved_settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "X-CSRF-Token",
            "Idempotency-Key",
            "X-Request-Id",
            "X-Workspace-Id",
        ],
    )
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(MonitoringError, monitoring_exception_handler)
    application.add_exception_handler(SyncError, sync_exception_handler)
    application.add_exception_handler(NewsError, news_exception_handler)
    application.add_exception_handler(EditorialRuleError, editorial_rule_exception_handler)
    application.add_exception_handler(GenerationError, generation_exception_handler)
    application.add_exception_handler(AutomationError, automation_exception_handler)
    application.add_exception_handler(SettingsError, settings_exception_handler)
    application.add_exception_handler(OutboxError, outbox_exception_handler)
    application.add_exception_handler(PlatformCredentialError, settings_exception_handler)
    application.add_exception_handler(
        NotificationTemplateError, notification_template_exception_handler
    )
    application.include_router(health_router)
    application.include_router(api_router)
    return application


app = create_app()
