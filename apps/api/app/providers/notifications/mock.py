from collections.abc import Mapping
from typing import Any

from app.providers.notifications.base import (
    NotificationHealth,
    NotificationMessage,
    NotificationProvider,
    NotificationReceipt,
    ProviderConfigField,
)


class MockNotificationProvider(NotificationProvider):
    key = "mock_notification"
    name = "Mock 通知（仅测试）"
    is_mock = True
    config_fields = (
        ProviderConfigField(
            "simulate_error",
            "模拟发送失败",
            "boolean",
            default=False,
            help_text="只用于测试错误处理；不会发送真实通知。",
        ),
    )

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        if config.get("simulate_error"):
            raise ValueError("Mock notification configured to simulate an error")

    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt:
        await self.validate_config(config)
        return NotificationReceipt(
            status="delivered",
            external_id=f"mock-{idempotency_key}",
            metadata={"source_kind": "mock", "test_output": True},
        )

    async def health_check(self, config: Mapping[str, Any]) -> NotificationHealth:
        await self.validate_config(config)
        return NotificationHealth(status="ok", detail="Mock provider is test-only")
