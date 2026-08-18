from app.core.config import Settings
from app.providers.notifications.base import NotificationProvider
from app.providers.notifications.email import EmailNotificationProvider
from app.providers.notifications.http import (
    DingTalkProvider,
    DiscordProvider,
    FeishuProvider,
    GenericWebhookProvider,
    TelegramProvider,
    WeComProvider,
)
from app.providers.registry import ProviderRegistry


def build_notification_provider_registry(
    settings: Settings,
) -> ProviderRegistry[NotificationProvider]:
    registry: ProviderRegistry[NotificationProvider] = ProviderRegistry()
    registry.register(EmailNotificationProvider())
    provider_types = (
        GenericWebhookProvider,
        TelegramProvider,
        DiscordProvider,
        FeishuProvider,
        DingTalkProvider,
        WeComProvider,
    )
    for provider_type in provider_types:
        registry.register(
            provider_type(
                timeout_seconds=settings.notification_request_timeout_seconds,
                max_attempts=settings.notification_request_max_attempts,
            )
        )
    return registry
