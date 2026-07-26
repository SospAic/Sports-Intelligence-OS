from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Mapping
from email.message import EmailMessage
from typing import Any

from email_validator import EmailNotValidError, validate_email

from app.providers.notifications.base import (
    NotificationAuthenticationError,
    NotificationConfigurationError,
    NotificationHealth,
    NotificationMessage,
    NotificationProvider,
    NotificationReceipt,
    NotificationTransientError,
    ProviderConfigField,
)


class EmailNotificationProvider(NotificationProvider):
    key = "email"
    name = "电子邮件"
    config_fields = (
        ProviderConfigField(
            "host", "SMTP 主机", "text", required=True, placeholder="smtp.example.com"
        ),
        ProviderConfigField(
            "port", "端口", "number", default=587, minimum=1, maximum=65535, step=1
        ),
        ProviderConfigField("username", "用户名", "text"),
        ProviderConfigField("password", "密码", "password", secret=True),
        ProviderConfigField("from_email", "发件人地址", "text", required=True),
        ProviderConfigField(
            "to_emails", "收件人", "list", required=True, help_text="1–50 个地址，每行或逗号分隔。"
        ),
        ProviderConfigField("reply_to", "Reply-To", "text"),
        ProviderConfigField("subject_prefix", "主题前缀", "text", placeholder="[Sports OS]"),
        ProviderConfigField("use_tls", "使用 STARTTLS", "boolean", default=True),
        ProviderConfigField("use_ssl", "使用隐式 SSL", "boolean", default=False),
        ProviderConfigField(
            "timeout_seconds",
            "连接/发送超时（秒）",
            "number",
            default=20,
            minimum=1,
            maximum=60,
            step=1,
        ),
    )

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        required = ("host", "from_email", "to_emails")
        for key in required:
            if not config.get(key):
                raise NotificationConfigurationError(f"{key} is required")
        recipients = config.get("to_emails")
        if not isinstance(recipients, list) or not recipients or len(recipients) > 50:
            raise NotificationConfigurationError("to_emails must contain 1 to 50 recipients")
        try:
            validate_email(str(config["from_email"]), check_deliverability=False)
            for recipient in recipients:
                validate_email(str(recipient), check_deliverability=False)
            if config.get("reply_to"):
                validate_email(str(config["reply_to"]), check_deliverability=False)
        except EmailNotValidError as exc:
            raise NotificationConfigurationError("email address is invalid") from exc
        for key in ("host", "subject_prefix", "username"):
            value = config.get(key)
            if value is not None and (not isinstance(value, str) or "\r" in value or "\n" in value):
                raise NotificationConfigurationError(f"{key} is invalid")
        port = config.get("port", 587)
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise NotificationConfigurationError("port must be between 1 and 65535")
        if bool(config.get("use_tls", True)) and bool(config.get("use_ssl", False)):
            raise NotificationConfigurationError("use_tls and use_ssl cannot both be enabled")
        for key in ("use_tls", "use_ssl"):
            if key in config and not isinstance(config[key], bool):
                raise NotificationConfigurationError(f"{key} must be boolean")
        timeout = config.get("timeout_seconds", 20)
        if not isinstance(timeout, (int, float)) or not 1 <= float(timeout) <= 60:
            raise NotificationConfigurationError("timeout_seconds must be between 1 and 60")

    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt:
        await self.validate_config(config)
        email = EmailMessage()
        prefix = str(config.get("subject_prefix") or "").strip()
        email["Subject"] = f"{prefix} {message.title}".strip()
        email["From"] = str(config["from_email"])
        email["To"] = ", ".join(str(item) for item in config["to_emails"])
        email["X-SIO-Idempotency-Key"] = idempotency_key
        if config.get("reply_to"):
            email["Reply-To"] = str(config["reply_to"])
        body = message.body + (f"\n\n{message.url}" if message.url else "")
        email.set_content(body)

        def deliver() -> None:
            host = str(config["host"])
            port = int(config.get("port", 587))
            smtp_class = smtplib.SMTP_SSL if config.get("use_ssl", False) else smtplib.SMTP
            with smtp_class(host, port, timeout=float(config.get("timeout_seconds", 20))) as client:
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
