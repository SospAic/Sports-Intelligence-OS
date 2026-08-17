from fastapi import APIRouter

from app.api.routes import (
    auth,
    automation,
    download,
    editorial,
    editorial_rules,
    generation,
    inbox,
    media,
    monitoring,
    news,
    operations,
    publications,
    reliability,
    semantic_search,
    settings,
    subscriptions,
    topics,
    trends,
    users,
    video_search,
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
api_router.include_router(inbox.router)
api_router.include_router(publications.router)
api_router.include_router(reliability.router)
api_router.include_router(settings.router)
api_router.include_router(subscriptions.router)
api_router.include_router(media.router)
api_router.include_router(download.router)
api_router.include_router(editorial.router)
api_router.include_router(video_search.router)
api_router.include_router(semantic_search.router)
