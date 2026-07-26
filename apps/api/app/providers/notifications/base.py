from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    body: str
    url: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationReceipt:
    status: Literal["delivered", "accepted"]
    external_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationHealth:
    status: Literal["ok", "degraded", "unavailable"]
    detail: str


class NotificationProviderError(RuntimeError):
    code = "notification_provider_error"
    retryable = False


class NotificationConfigurationError(NotificationProviderError):
    code = "notification_configuration_error"


class NotificationAuthenticationError(NotificationProviderError):
    code = "notification_authentication_error"


class NotificationRateLimitError(NotificationProviderError):
    code = "notification_rate_limited"
    retryable = True


class NotificationTransientError(NotificationProviderError):
    code = "notification_transient_error"
    retryable = True


class NotificationPermanentError(NotificationProviderError):
    code = "notification_permanent_error"


class NotificationProvider(ABC):
    key: str
    name: str
    is_mock: bool = False

    @abstractmethod
    async def validate_config(self, config: Mapping[str, Any]) -> None: ...

    @abstractmethod
    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt: ...

    async def test(self, config: Mapping[str, Any]) -> NotificationReceipt:
        await self.validate_config(config)
        return await self.send(
            config,
            NotificationMessage(
                title="Sports Intelligence OS 测试通知",
                body="通知渠道配置测试成功。",
                data={"test": True},
            ),
            idempotency_key="channel-test",
        )

    @abstractmethod
    async def health_check(self, config: Mapping[str, Any]) -> NotificationHealth: ...
