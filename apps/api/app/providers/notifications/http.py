from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.providers.news.utils import ensure_public_endpoint, validate_source_url
from app.providers.notifications.base import (
    NotificationAuthenticationError,
    NotificationConfigurationError,
    NotificationHealth,
    NotificationMessage,
    NotificationPermanentError,
    NotificationProvider,
    NotificationRateLimitError,
    NotificationReceipt,
    NotificationTransientError,
    ProviderConfigField,
)


class HTTPNotificationProvider(NotificationProvider):
    def __init__(self, *, timeout_seconds: float, max_attempts: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._client = httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health_check(self, config: Mapping[str, Any]) -> NotificationHealth:
        await self.validate_config(config)
        return NotificationHealth(
            status="ok", detail="Configuration is valid; no notification was sent"
        )

    async def _post(
        self,
        url: str,
        *,
        json_body: Mapping[str, Any],
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
    ) -> httpx.Response:
        try:
            await ensure_public_endpoint(url, allow_secret_query=True)
        except ValueError as exc:
            raise NotificationConfigurationError(str(exc)) from exc
        except OSError as exc:
            raise NotificationTransientError(str(exc)) from exc
        timeout = timeout_seconds if timeout_seconds is not None else self._timeout_seconds
        attempts = max_attempts if max_attempts is not None else self._max_attempts
        if not 1 <= timeout <= 60:
            raise NotificationConfigurationError("timeout_seconds must be between 1 and 60")
        if not 1 <= attempts <= 5:
            raise NotificationConfigurationError("max_attempts must be between 1 and 5")
        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.post(
                    url, json=json_body, headers=headers, timeout=timeout
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == attempts:
                    raise NotificationTransientError(
                        "notification endpoint is unavailable"
                    ) from None
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
                continue
            if response.status_code in {401, 403}:
                raise NotificationAuthenticationError("notification endpoint rejected credentials")
            if response.status_code == 429:
                if attempt == attempts:
                    raise NotificationRateLimitError(
                        "notification endpoint rate limited the request"
                    )
                await asyncio.sleep(min(0.5 * (2 ** (attempt - 1)), 3.0))
                continue
            if response.status_code >= 500:
                if attempt == attempts:
                    raise NotificationTransientError(
                        "notification endpoint returned a server error"
                    )
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
                continue
            if response.status_code >= 400:
                raise NotificationPermanentError(
                    f"notification endpoint rejected the payload ({response.status_code})"
                )
            return response
        raise NotificationTransientError("notification endpoint is unavailable")

    def _request_options(self, config: Mapping[str, Any]) -> tuple[float, int]:
        try:
            timeout = float(config.get("timeout_seconds", self._timeout_seconds))
            attempts = int(config.get("max_attempts", self._max_attempts))
        except (TypeError, ValueError) as exc:
            raise NotificationConfigurationError(
                "timeout_seconds and max_attempts must be numeric"
            ) from exc
        if not 1 <= timeout <= 60 or not 1 <= attempts <= 5:
            raise NotificationConfigurationError(
                "timeout_seconds must be 1–60 and max_attempts must be 1–5"
            )
        return timeout, attempts


class GenericWebhookProvider(HTTPNotificationProvider):
    key = "generic_webhook"
    name = "通用 Webhook"
    config_fields = (
        ProviderConfigField("url", "Webhook URL", "text", required=True),
        ProviderConfigField("headers", "附加请求头", "json", secret=True, default={}),
        ProviderConfigField("signing_secret", "HMAC 签名密钥", "password", secret=True),
        ProviderConfigField(
            "timeout_seconds", "请求超时（秒）", "number", default=10, minimum=1, maximum=60, step=1
        ),
        ProviderConfigField(
            "max_attempts", "最大尝试次数", "number", default=3, minimum=1, maximum=5, step=1
        ),
    )

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        url = config.get("url")
        if not isinstance(url, str):
            raise NotificationConfigurationError("url is required")
        try:
            validate_source_url(url, allow_secret_query=True)
        except ValueError as exc:
            raise NotificationConfigurationError(str(exc)) from exc
        headers = config.get("headers", {})
        if not isinstance(headers, Mapping) or len(headers) > 20:
            raise NotificationConfigurationError("headers must be an object with up to 20 entries")
        for key, value in headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise NotificationConfigurationError("header names and values must be strings")
            if key.casefold() in {"host", "content-length"}:
                raise NotificationConfigurationError(f"header is not allowed: {key}")
            if len(key) > 120 or len(value) > 2048 or "\r" in value or "\n" in value:
                raise NotificationConfigurationError("header is invalid or too long")
        self._request_options(config)

    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt:
        await self.validate_config(config)
        body = {
            "title": message.title,
            "body": message.body,
            "url": message.url,
            "data": dict(message.data),
            "idempotency_key": idempotency_key,
        }
        headers = {str(key): str(value) for key, value in dict(config.get("headers", {})).items()}
        headers["Idempotency-Key"] = idempotency_key
        secret = config.get("signing_secret")
        if isinstance(secret, str) and secret:
            payload = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
            headers["X-SIO-Signature-SHA256"] = hmac.new(
                secret.encode("utf-8"), payload, hashlib.sha256
            ).hexdigest()
        timeout, attempts = self._request_options(config)
        response = await self._post(
            str(config["url"]),
            json_body=body,
            headers=headers,
            timeout_seconds=timeout,
            max_attempts=attempts,
        )
        return NotificationReceipt(
            status="delivered",
            external_id=response.headers.get("X-Request-Id"),
            metadata={"http_status": response.status_code},
        )


class TelegramProvider(HTTPNotificationProvider):
    key = "telegram"
    name = "Telegram"
    config_fields = (
        ProviderConfigField("bot_token", "Bot Token", "password", required=True, secret=True),
        ProviderConfigField("chat_id", "Chat ID", "text", required=True),
        ProviderConfigField(
            "parse_mode",
            "解析模式",
            "select",
            default="none",
            options=(("none", "纯文本"), ("HTML", "HTML"), ("MarkdownV2", "MarkdownV2")),
        ),
        ProviderConfigField("disable_web_page_preview", "禁用链接预览", "boolean", default=False),
        ProviderConfigField("disable_notification", "静默通知", "boolean", default=False),
        ProviderConfigField("message_thread_id", "Topic / Thread ID", "number", minimum=1, step=1),
        ProviderConfigField(
            "timeout_seconds", "请求超时（秒）", "number", default=10, minimum=1, maximum=60, step=1
        ),
        ProviderConfigField(
            "max_attempts", "最大尝试次数", "number", default=3, minimum=1, maximum=5, step=1
        ),
    )

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        if not isinstance(config.get("bot_token"), str) or not config.get("bot_token"):
            raise NotificationConfigurationError("bot_token is required")
        if not isinstance(config.get("chat_id"), (str, int)):
            raise NotificationConfigurationError("chat_id is required")
        if not str(config["chat_id"]).strip():
            raise NotificationConfigurationError("chat_id is required")
        if config.get("parse_mode", "none") not in {"none", "HTML", "MarkdownV2"}:
            raise NotificationConfigurationError("parse_mode is invalid")
        for key in ("disable_web_page_preview", "disable_notification"):
            if key in config and not isinstance(config[key], bool):
                raise NotificationConfigurationError(f"{key} must be boolean")
        thread_id = config.get("message_thread_id")
        if thread_id is not None and (
            not isinstance(thread_id, int) or isinstance(thread_id, bool) or thread_id < 1
        ):
            raise NotificationConfigurationError("message_thread_id must be a positive integer")
        self._request_options(config)

    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt:
        await self.validate_config(config)
        token = str(config["bot_token"])
        text = f"{message.title}\n\n{message.body}"
        if message.url:
            text += f"\n{message.url}"
        telegram_body: dict[str, Any] = {
            "chat_id": config["chat_id"],
            "text": text[:4096],
            "disable_web_page_preview": bool(config.get("disable_web_page_preview", False)),
            "disable_notification": bool(config.get("disable_notification", False)),
        }
        if config.get("parse_mode") not in {None, "none"}:
            telegram_body["parse_mode"] = config["parse_mode"]
        if config.get("message_thread_id"):
            telegram_body["message_thread_id"] = int(config["message_thread_id"])
        timeout, attempts = self._request_options(config)
        response = await self._post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json_body=telegram_body,
            headers={"Idempotency-Key": idempotency_key},
            timeout_seconds=timeout,
            max_attempts=attempts,
        )
        external_id: str | None = None
        try:
            payload = response.json()
            if payload.get("ok") is not True:
                raise NotificationPermanentError("Telegram rejected the notification payload")
            external_id = str(payload.get("result", {}).get("message_id") or "") or None
        except (ValueError, AttributeError):
            pass
        return NotificationReceipt(status="delivered", external_id=external_id)


class ChatWebhookProvider(HTTPNotificationProvider):
    payload_kind: str

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        url = config.get("webhook_url")
        if not isinstance(url, str):
            raise NotificationConfigurationError("webhook_url is required")
        try:
            validate_source_url(url, allow_secret_query=True)
        except ValueError as exc:
            raise NotificationConfigurationError(str(exc)) from exc
        boolean_fields = {
            "discord": ("tts",),
            "feishu": ("at_all",),
            "dingtalk": ("at_all",),
        }.get(self.payload_kind, ())
        for key in boolean_fields:
            if key in config and not isinstance(config[key], bool):
                raise NotificationConfigurationError(f"{key} must be boolean")
        list_fields = {
            "dingtalk": ("at_mobiles",),
            "wecom": ("mentioned_list", "mentioned_mobile_list"),
        }.get(self.payload_kind, ())
        for key in list_fields:
            value = config.get(key, [])
            if (
                not isinstance(value, list)
                or len(value) > 50
                or not all(isinstance(item, str) and 0 < len(item) <= 128 for item in value)
            ):
                raise NotificationConfigurationError(f"{key} must be a list of up to 50 strings")
        if self.payload_kind == "discord":
            username = config.get("username")
            if username is not None and (not isinstance(username, str) or len(username) > 80):
                raise NotificationConfigurationError("username must be at most 80 characters")
        self._request_options(config)

    def build_payload(self, message: NotificationMessage) -> dict[str, Any]:
        text = f"{message.title}\n{message.body}"
        if message.url:
            text += f"\n{message.url}"
        if self.payload_kind == "discord":
            payload: dict[str, Any] = {"content": text[:2000]}
            if message.data.get("username"):
                payload["username"] = str(message.data["username"])[:80]
            return payload
        if self.payload_kind == "feishu":
            return {"msg_type": "text", "content": {"text": text}}
        return {"msgtype": "text", "text": {"content": text}}

    async def send(
        self,
        config: Mapping[str, Any],
        message: NotificationMessage,
        *,
        idempotency_key: str,
    ) -> NotificationReceipt:
        await self.validate_config(config)
        body = self.build_payload(message)
        if self.payload_kind == "discord":
            if config.get("username"):
                body["username"] = str(config["username"])[:80]
            if config.get("avatar_url"):
                body["avatar_url"] = str(config["avatar_url"])
            body["tts"] = bool(config.get("tts", False))
        elif self.payload_kind == "feishu" and config.get("at_all"):
            body["content"]["text"] = f'<at user_id="all">所有人</at> {body["content"]["text"]}'
        elif self.payload_kind == "dingtalk":
            body["at"] = {
                "atMobiles": list(config.get("at_mobiles") or []),
                "isAtAll": bool(config.get("at_all", False)),
            }
        elif self.payload_kind == "wecom":
            body["text"]["mentioned_list"] = list(config.get("mentioned_list") or [])
            body["text"]["mentioned_mobile_list"] = list(config.get("mentioned_mobile_list") or [])
        url = str(config["webhook_url"])
        secret = config.get("secret")
        if self.payload_kind == "dingtalk" and isinstance(secret, str) and secret:
            timestamp = str(int(time.time() * 1000))
            signature = base64.b64encode(
                hmac.new(
                    secret.encode(),
                    f"{timestamp}\n{secret}".encode(),
                    hashlib.sha256,
                ).digest()
            ).decode()
            parsed = urlsplit(url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query.update({"timestamp": timestamp, "sign": signature})
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        elif self.payload_kind == "feishu" and isinstance(secret, str) and secret:
            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{secret}"
            signature = base64.b64encode(
                hmac.new(
                    string_to_sign.encode(),
                    digestmod=hashlib.sha256,
                ).digest()
            ).decode()
            body = {**body, "timestamp": timestamp, "sign": signature}
        timeout, attempts = self._request_options(config)
        response = await self._post(
            url,
            json_body=body,
            headers={"Idempotency-Key": idempotency_key},
            timeout_seconds=timeout,
            max_attempts=attempts,
        )
        if self.payload_kind != "discord":
            try:
                result = response.json()
            except ValueError:
                result = {}
            error_code = result.get("errcode", result.get("code", 0))
            if error_code not in {0, "0", None}:
                raise NotificationPermanentError(f"{self.name} rejected the notification payload")
        return NotificationReceipt(
            status="delivered", metadata={"http_status": response.status_code}
        )


class DiscordProvider(ChatWebhookProvider):
    key = "discord"
    name = "Discord"
    payload_kind = "discord"
    config_fields = (
        ProviderConfigField("webhook_url", "Webhook URL", "text", required=True, secret=True),
        ProviderConfigField("username", "机器人显示名称", "text"),
        ProviderConfigField("avatar_url", "头像 URL", "text"),
        ProviderConfigField("tts", "启用 TTS", "boolean", default=False),
        ProviderConfigField(
            "timeout_seconds", "请求超时（秒）", "number", default=10, minimum=1, maximum=60, step=1
        ),
        ProviderConfigField(
            "max_attempts", "最大尝试次数", "number", default=3, minimum=1, maximum=5, step=1
        ),
    )


class FeishuProvider(ChatWebhookProvider):
    key = "feishu"
    name = "飞书"
    payload_kind = "feishu"
    config_fields = (
        ProviderConfigField("webhook_url", "Webhook URL", "text", required=True, secret=True),
        ProviderConfigField("secret", "签名密钥", "password", secret=True),
        ProviderConfigField("at_all", "提醒所有人", "boolean", default=False),
        ProviderConfigField(
            "timeout_seconds", "请求超时（秒）", "number", default=10, minimum=1, maximum=60, step=1
        ),
        ProviderConfigField(
            "max_attempts", "最大尝试次数", "number", default=3, minimum=1, maximum=5, step=1
        ),
    )


class DingTalkProvider(ChatWebhookProvider):
    key = "dingtalk"
    name = "钉钉"
    payload_kind = "dingtalk"
    config_fields = (
        ProviderConfigField("webhook_url", "Webhook URL", "text", required=True, secret=True),
        ProviderConfigField("secret", "加签密钥", "password", secret=True),
        ProviderConfigField("at_mobiles", "@ 手机号", "list"),
        ProviderConfigField("at_all", "提醒所有人", "boolean", default=False),
        ProviderConfigField(
            "timeout_seconds", "请求超时（秒）", "number", default=10, minimum=1, maximum=60, step=1
        ),
        ProviderConfigField(
            "max_attempts", "最大尝试次数", "number", default=3, minimum=1, maximum=5, step=1
        ),
    )


class WeComProvider(ChatWebhookProvider):
    key = "wecom"
    name = "企业微信"
    payload_kind = "wecom"
    config_fields = (
        ProviderConfigField("webhook_url", "Webhook URL", "text", required=True, secret=True),
        ProviderConfigField("mentioned_list", "@ 用户 ID", "list"),
        ProviderConfigField("mentioned_mobile_list", "@ 手机号", "list"),
        ProviderConfigField(
            "timeout_seconds", "请求超时（秒）", "number", default=10, minimum=1, maximum=60, step=1
        ),
        ProviderConfigField(
            "max_attempts", "最大尝试次数", "number", default=3, minimum=1, maximum=5, step=1
        ),
    )
