from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Any

from app.providers.notifications.base import (
    NotificationAuthenticationError,
    NotificationConfigurationError,
    NotificationHealth,
    NotificationMessage,
    NotificationProvider,
    NotificationReceipt,
    NotificationTransientError,
)


class EmailNotificationProvider(NotificationProvider):
    key = "email"
    name = "电子邮件"

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        required = ("host", "from_email", "to_emails")
        for key in required:
            if not config.get(key):
                raise NotificationConfigurationError(f"{key} is required")
        recipients = config.get("to_emails")
        if not isinstance(recipients, list) or not recipients or len(recipients) > 50:
            raise NotificationConfigurationError("to_emails must contain 1 to 50 recipients")
        port = config.get("port", 587)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise NotificationConfigurationError("port must be between 1 and 65535")
        if bool(config.get("use_tls", True)) and bool(config.get("use_ssl", False)):
            raise NotificationConfigurationError("use_tls and use_ssl cannot both be enabled")

    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt:
        await self.validate_config(config)
        email = EmailMessage()
        email["Subject"] = message.title
        email["From"] = str(config["from_email"])
        email["To"] = ", ".join(str(item) for item in config["to_emails"])
        email["X-SIO-Idempotency-Key"] = idempotency_key
        body = message.body + (f"\n\n{message.url}" if message.url else "")
        email.set_content(body)

        def deliver() -> None:
            host = str(config["host"])
            port = int(config.get("port", 587))
            smtp_class = smtplib.SMTP_SSL if config.get("use_ssl", False) else smtplib.SMTP
            with smtp_class(host, port, timeout=20) as client:
                if config.get("use_tls", True):
                    client.starttls()
                username = config.get("username")
                password = config.get("password")
                if username:
                    client.login(str(username), str(password or ""))
                client.send_message(email)

        try:
            await asyncio.to_thread(deliver)
        except smtplib.SMTPAuthenticationError as exc:
            raise NotificationAuthenticationError("SMTP authentication failed") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise NotificationTransientError("SMTP delivery failed") from exc
        return NotificationReceipt(status="delivered")

    async def health_check(self, config: Mapping[str, Any]) -> NotificationHealth:
        await self.validate_config(config)
        return NotificationHealth(status="ok", detail="Configuration is valid; no email was sent")
