from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken


class SecretConfigCipher:
    def __init__(self, secret: str) -> None:
        if len(secret) < 16:
            raise ValueError("notification encryption material is too short")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, config: Mapping[str, Any]) -> str:
        raw = json.dumps(dict(config), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw).decode("ascii")

    def decrypt(self, token: str) -> dict[str, Any]:
        try:
            raw = self._fernet.decrypt(token.encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise ValueError("encrypted configuration cannot be decrypted") from exc
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("notification channel configuration is invalid")
        return value


SECRET_PARTS = ("password", "secret", "token", "key", "authorization")


def mask_secret_config(config: Mapping[str, Any]) -> dict[str, Any]:
    def mask(key: str, value: Any) -> Any:
        lowered = key.casefold()
        if lowered in {"headers", "custom_headers"} and isinstance(value, Mapping):
            return {
                str(child_key): "••••••••" if child else None for child_key, child in value.items()
            }
        if any(part in lowered for part in SECRET_PARTS):
            return "••••••••" if value else None
        if lowered.endswith("url") and isinstance(value, str):
            parsed = urlsplit(value)
            if parsed.scheme and parsed.hostname:
                port = f":{parsed.port}" if parsed.port else ""
                return f"{parsed.scheme}://{parsed.hostname}{port}/••••"
            return "••••••••"
        if isinstance(value, Mapping):
            return {
                str(child_key): mask(str(child_key), child) for child_key, child in value.items()
            }
        if isinstance(value, list):
            return [mask(key, child) for child in value]
        return value

    return {str(key): mask(str(key), value) for key, value in config.items()}


# Backward-compatible names retained for the notification domain.
NotificationConfigCipher = SecretConfigCipher
mask_notification_config = mask_secret_config
