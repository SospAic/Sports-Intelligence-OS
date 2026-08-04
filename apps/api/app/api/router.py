from fastapi import APIRouter

from app.api.routes import (
    auth,
    automation,
    download,
    editorial_rules,
    generation,
    media,
    monitoring,
    news,
    operations,
    reliability,
    settings,
    topics,
    trends,
    users,
    view_preferences,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(view_preferences.router)
api_router.include_router(monitoring.router)
api_router.include_router(news.router)
api_router.include_router(editorial_rules.router)
api_router.include_router(generation.router)
api_router.include_router(automation.router)
api_router.include_router(topics.router)
api_router.include_router(trends.router)
api_router.include_router(operations.router)
api_router.include_router(reliability.router)
api_router.include_router(settings.router)
api_router.include_router(media.router)
api_router.include_router(download.router)
