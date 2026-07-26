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
    ) -> httpx.Response:
        try:
            await ensure_public_endpoint(url, allow_secret_query=True)
        except ValueError as exc:
            raise NotificationConfigurationError(str(exc)) from exc
        except OSError as exc:
            raise NotificationTransientError(str(exc)) from exc
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.post(url, json=json_body, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == self._max_attempts:
                    raise NotificationTransientError(
                        "notification endpoint is unavailable"
                    ) from None
                await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
                continue
            if response.status_code in {401, 403}:
                raise NotificationAuthenticationError("notification endpoint rejected credentials")
            if response.status_code == 429:
                if attempt == self._max_attempts:
                    raise NotificationRateLimitError(
                        "notification endpoint rate limited the request"
                    )
                await asyncio.sleep(min(0.5 * (2 ** (attempt - 1)), 3.0))
                continue
            if response.status_code >= 500:
                if attempt == self._max_attempts:
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


class GenericWebhookProvider(HTTPNotificationProvider):
    key = "generic_webhook"
    name = "通用 Webhook"

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
        response = await self._post(str(config["url"]), json_body=body, headers=headers)
        return NotificationReceipt(
            status="delivered",
            external_id=response.headers.get("X-Request-Id"),
            metadata={"http_status": response.status_code},
        )


class TelegramProvider(HTTPNotificationProvider):
    key = "telegram"
    name = "Telegram"

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        if not isinstance(config.get("bot_token"), str) or not config.get("bot_token"):
            raise NotificationConfigurationError("bot_token is required")
        if not isinstance(config.get("chat_id"), (str, int)):
            raise NotificationConfigurationError("chat_id is required")

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
        response = await self._post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json_body={"chat_id": config["chat_id"], "text": text[:4096]},
            headers={"Idempotency-Key": idempotency_key},
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

    def build_payload(self, message: NotificationMessage) -> dict[str, Any]:
        text = f"{message.title}\n{message.body}"
        if message.url:
            text += f"\n{message.url}"
        if self.payload_kind == "discord":
            return {"content": text[:2000]}
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
        response = await self._post(
            url,
            json_body=body,
            headers={"Idempotency-Key": idempotency_key},
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


class FeishuProvider(ChatWebhookProvider):
    key = "feishu"
    name = "飞书"
    payload_kind = "feishu"


class DingTalkProvider(ChatWebhookProvider):
    key = "dingtalk"
    name = "钉钉"
    payload_kind = "dingtalk"


class WeComProvider(ChatWebhookProvider):
    key = "wecom"
    name = "企业微信"
    payload_kind = "wecom"
