from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.monitoring import Platform
from app.models.operations import AuditEntry
from app.models.settings import PlatformCredentialSetting
from app.providers.notifications.crypto import SecretConfigCipher, mask_secret_config
from app.schemas.settings import PlatformCredentialRead, PlatformCredentialUpdate

API_FIELDS: dict[str, set[str]] = {
    "youtube": {"api_key"},
    "tiktok": {"client_key", "client_secret", "access_token", "refresh_token"},
    "douyin": {"client_key", "client_secret", "access_token", "refresh_token"},
    "bilibili": set(),
}
REQUIRED_API_FIELDS: dict[str, set[str]] = {
    "youtube": {"api_key"},
    "tiktok": {"client_key", "client_secret", "access_token"},
    "douyin": {"client_key", "client_secret", "access_token"},
    "bilibili": set(),
}
API_SUPPORTED = frozenset({"youtube", "tiktok", "douyin"})
MANAGED_PLATFORM_KEYS = frozenset(API_FIELDS)
PUBLIC_PAGE_FIELDS = {
    "terms_permission_confirmed",
    "robots_reviewed",
    "fields_minimized",
    "source_audit_enabled",
    "sample_interval_seconds",
}
PUBLIC_PAGE_CONFIRMATIONS = PUBLIC_PAGE_FIELDS - {"sample_interval_seconds"}
MIN_PUBLIC_SAMPLE_INTERVAL_SECONDS = 300
AUTHORIZED_LOGIN_FIELDS = {
    "username",
    "password",
    "account_authorization_confirmed",
    "platform_login_allowed",
    "oauth_unavailable_or_insufficient",
}
AUTHORIZED_LOGIN_CONFIRMATIONS = {
    "account_authorization_confirmed",
    "platform_login_allowed",
    "oauth_unavailable_or_insufficient",
}
AUTHORIZED_SESSION_FIELDS = {
    "storage_state_json",
    "session_label",
    "session_expires_at",
    "account_authorization_confirmed",
    "platform_session_allowed",
    "oauth_unavailable_or_insufficient",
}
AUTHORIZED_SESSION_CONFIRMATIONS = {
    "account_authorization_confirmed",
    "platform_session_allowed",
    "oauth_unavailable_or_insufficient",
}
# Residential/rotating proxy used to bypass datacenter-IP anti-bot walls.
# Allowed in every mode so a workspace can attach a proxy to any acquisition
# strategy (notably for TikTok/Douyin public-page and authorized-session runs).
PROXY_FIELDS = {
    "proxy_server",
    "proxy_username",
    "proxy_password",
}

# Runtime connection hints that let the project reuse the operator's REAL local
# browser (Chrome/Edge) to bypass datacenter-headless anti-bot walls on
# TikTok/Douyin. Allowed in every mode; not secrets.
LOCAL_BROWSER_FIELDS = {
    "cdp_endpoint",
    "launch_mode",
    "browser_channel",
    "browser_executable_path",
    "user_data_dir",
}


class PlatformCredentialError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class PlatformCredentialService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        explicit_key = (
            settings.notification_encryption_key.get_secret_value()
            if settings.notification_encryption_key
            else ""
        )
        self.cipher = SecretConfigCipher(explicit_key or settings.secret_key.get_secret_value())

    async def list(self, workspace_id: UUID) -> list[PlatformCredentialRead]:
        platform_keys = list(
            (
                await self.session.scalars(
                    select(Platform.key).where(Platform.enabled.is_(True)).order_by(Platform.name)
                )
            ).all()
        )
        return [await self.get(workspace_id, key) for key in platform_keys]

    async def get(self, workspace_id: UUID, platform_key: str) -> PlatformCredentialRead:
        key = await self._validate_platform(platform_key)
        row = await self._row(workspace_id, key)
        return self._read(key, row)

    async def update(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        platform_key: str,
        payload: PlatformCredentialUpdate,
    ) -> PlatformCredentialRead:
        key = await self._validate_platform(platform_key)
        allowed = (
            API_FIELDS.get(key, set())
            | PUBLIC_PAGE_FIELDS
            | AUTHORIZED_LOGIN_FIELDS
            | AUTHORIZED_SESSION_FIELDS
            | PROXY_FIELDS
            | LOCAL_BROWSER_FIELDS
        )
        unknown = (set(payload.config) | set(payload.clear_fields)) - allowed
        if unknown:
            raise PlatformCredentialError(
                "unsupported credential fields: " + ", ".join(sorted(unknown)),
                code="platform_credential_fields_invalid",
                status_code=422,
            )

        row = await self._row(workspace_id, key)
        existing = self.cipher.decrypt(row.config_encrypted) if row else {}
        config = {**existing, **payload.config}
        for field in payload.clear_fields:
            config.pop(field, None)
        if payload.mode == "public_page":
            missing_confirmations = sorted(
                field
                for field in PUBLIC_PAGE_CONFIRMATIONS
                if config.get(field, "").casefold() != "true"
            )
            try:
                interval = int(config.get("sample_interval_seconds", "0"))
            except ValueError:
                interval = 0
            if missing_confirmations or interval < MIN_PUBLIC_SAMPLE_INTERVAL_SECONDS:
                raise PlatformCredentialError(
                    "public-page collection requires terms/permission, robots, "
                    "field-minimization and source-audit confirmations plus a sample "
                    f"interval of at least {MIN_PUBLIC_SAMPLE_INTERVAL_SECONDS} seconds",
                    code="public_page_policy_incomplete",
                    status_code=422,
                )
        elif payload.mode == "authorized_login":
            if not all(
                config.get(field, "").casefold() == "true"
                for field in AUTHORIZED_LOGIN_CONFIRMATIONS
            ):
                raise PlatformCredentialError(
                    "authorized login requires account ownership, platform permission "
                    "and OAuth-unavailable confirmations",
                    code="authorized_login_policy_incomplete",
                    status_code=422,
                )
            if not config.get("username") or not config.get("password"):
                raise PlatformCredentialError(
                    "authorized login requires both username and password",
                    code="authorized_login_credentials_required",
                    status_code=422,
                )
        elif payload.mode == "authorized_session":
            if not all(
                config.get(field, "").casefold() == "true"
                for field in AUTHORIZED_SESSION_CONFIRMATIONS
            ):
                raise PlatformCredentialError(
                    "authorized session requires account ownership, platform permission "
                    "and OAuth-unavailable confirmations",
                    code="authorized_session_policy_incomplete",
                    status_code=422,
                )
            self._validate_storage_state(config)
        else:
            if key not in API_SUPPORTED:
                raise PlatformCredentialError(
                    "this platform has no registered official API provider",
                    code="platform_api_unavailable",
                    status_code=422,
                )
            missing = REQUIRED_API_FIELDS.get(key, set()) - {
                field for field, value in config.items() if value
            }
            if missing:
                raise PlatformCredentialError(
                    "missing required API credential fields: " + ", ".join(sorted(missing)),
                    code="platform_credential_incomplete",
                    status_code=422,
                )

        if row is None:
            row = PlatformCredentialSetting(
                id=uuid4(),
                workspace_id=workspace_id,
                platform_key=key,
                mode=payload.mode,
                config_encrypted=self.cipher.encrypt(config),
                config_masked=self._masked_config(config),
                enabled=payload.enabled,
            )
            self.session.add(row)
            action = "platform_credential.created"
        else:
            row.mode = payload.mode
            row.config_encrypted = self.cipher.encrypt(config)
            row.config_masked = self._masked_config(config)
            row.enabled = payload.enabled
            action = "platform_credential.updated"

        self._audit(
            workspace_id,
            actor_id,
            action,
            row.id,
            {
                "platform_key": key,
                "mode": payload.mode,
                "enabled": payload.enabled,
                "configured_fields": sorted(config),
            },
        )
        await self.session.commit()
        await self.session.refresh(row)
        return self._read(key, row)

    async def resolve(
        self, workspace_id: UUID, platform_key: str
    ) -> tuple[str, dict[str, Any]]:
        key = platform_key.removesuffix("_browser")
        row = await self._row(workspace_id, key)
        if row is not None and self._read(key, row).configured:
            config = self.cipher.decrypt(row.config_encrypted)
            fields = {
                "api": API_FIELDS.get(key, set()),
                "public_page": PUBLIC_PAGE_FIELDS,
                "authorized_login": AUTHORIZED_LOGIN_FIELDS,
                "authorized_session": AUTHORIZED_SESSION_FIELDS,
            }[row.mode]
            return row.mode, {
                field: value for field, value in config.items() if field in fields
            }
        if key == "youtube" and self.settings.youtube_api_key is not None:
            return "api", {"api_key": self.settings.youtube_api_key.get_secret_value()}
        return "unconfigured", {}

    async def _validate_platform(self, platform_key: str) -> str:
        key = platform_key.strip().casefold().removesuffix("_browser")
        exists = await self.session.scalar(
            select(Platform.id).where(Platform.key == key, Platform.enabled.is_(True))
        )
        if exists is None:
            raise PlatformCredentialError(
                "platform was not found", code="platform_not_found", status_code=404
            )
        return key

    async def _row(
        self, workspace_id: UUID, platform_key: str
    ) -> PlatformCredentialSetting | None:
        return cast(
            PlatformCredentialSetting | None,
            await self.session.scalar(
                select(PlatformCredentialSetting).where(
                    PlatformCredentialSetting.workspace_id == workspace_id,
                    PlatformCredentialSetting.platform_key == platform_key,
                )
            ),
        )

    def _read(
        self, platform_key: str, row: PlatformCredentialSetting | None
    ) -> PlatformCredentialRead:
        if row is not None:
            config = self.cipher.decrypt(row.config_encrypted)
            required = REQUIRED_API_FIELDS.get(platform_key, set())
            try:
                sample_interval = int(config.get("sample_interval_seconds", "0"))
            except (TypeError, ValueError):
                sample_interval = 0
            public_policy_valid = bool(
                all(
                    str(config.get(field, "")).casefold() == "true"
                    for field in PUBLIC_PAGE_CONFIRMATIONS
                )
                and sample_interval >= MIN_PUBLIC_SAMPLE_INTERVAL_SECONDS
            )
            authorized_login_valid = bool(
                config.get("username")
                and config.get("password")
                and all(
                    str(config.get(field, "")).casefold() == "true"
                    for field in AUTHORIZED_LOGIN_CONFIRMATIONS
                )
            )
            authorized_session_valid = self._authorized_session_valid(config)
            configured = bool(
                row.enabled
                and (
                    (row.mode == "public_page" and public_policy_valid)
                    or (row.mode == "authorized_login" and authorized_login_valid)
                    or (row.mode == "authorized_session" and authorized_session_valid)
                    or (
                        row.mode == "api"
                        and platform_key in API_SUPPORTED
                        and all(config.get(field) for field in required)
                    )
                )
            )
            return PlatformCredentialRead(
                platform_key=platform_key,
                mode=cast(Any, row.mode),
                source="database",
                enabled=row.enabled,
                configured=configured,
                configured_fields=sorted(field for field, value in config.items() if value),
                config_masked=row.config_masked,
                updated_at=row.updated_at,
            )
        if platform_key == "youtube" and self.settings.youtube_api_key is not None:
            return PlatformCredentialRead(
                platform_key=platform_key,
                mode="api",
                source="environment",
                enabled=True,
                configured=True,
                configured_fields=["api_key"],
                config_masked={"api_key": "configured"},
                updated_at=None,
            )
        return PlatformCredentialRead(
            platform_key=platform_key,
            mode="public_page",
            source="default",
            enabled=False,
            configured=False,
            configured_fields=[],
            config_masked={},
            updated_at=None,
        )

    async def revoke_login_access(
        self, workspace_id: UUID, actor_id: UUID, platform_key: str
    ) -> PlatformCredentialRead:
        key = await self._validate_platform(platform_key)
        row = await self._row(workspace_id, key)
        if row is None:
            raise PlatformCredentialError(
                "platform acquisition settings were not found",
                code="platform_credential_not_found",
                status_code=404,
            )
        config = self.cipher.decrypt(row.config_encrypted)
        removed = sorted(
            field
            for field in (AUTHORIZED_LOGIN_FIELDS | AUTHORIZED_SESSION_FIELDS)
            if config.pop(field, None) is not None
        )
        api_ready = key in API_SUPPORTED and all(
            config.get(field) for field in REQUIRED_API_FIELDS[key]
        )
        try:
            public_interval = int(config.get("sample_interval_seconds", "0"))
        except (TypeError, ValueError):
            public_interval = 0
        public_ready = (
            all(
                str(config.get(field, "")).casefold() == "true"
                for field in PUBLIC_PAGE_CONFIRMATIONS
            )
            and public_interval >= MIN_PUBLIC_SAMPLE_INTERVAL_SECONDS
        )
        if api_ready:
            row.mode = "api"
            row.enabled = True
        elif public_ready:
            row.mode = "public_page"
            row.enabled = True
        else:
            row.mode = "public_page"
            row.enabled = False
        row.config_encrypted = self.cipher.encrypt(config)
        row.config_masked = self._masked_config(config)
        self._audit(
            workspace_id,
            actor_id,
            "platform_login_access.revoked",
            row.id,
            {"platform_key": key, "removed_fields": removed, "fallback": row.mode},
        )
        await self.session.commit()
        await self.session.refresh(row)
        return self._read(key, row)

    @staticmethod
    def _validate_storage_state(config: dict[str, Any]) -> None:
        raw = config.get("storage_state_json")
        if not isinstance(raw, str) or not raw:
            raise PlatformCredentialError(
                "an exported Playwright storage-state JSON document is required",
                code="authorized_session_state_required",
                status_code=422,
            )
        try:
            state = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PlatformCredentialError(
                "storage-state JSON is invalid",
                code="authorized_session_state_invalid",
                status_code=422,
            ) from exc
        if not isinstance(state, dict) or not isinstance(state.get("cookies", []), list):
            raise PlatformCredentialError(
                "storage-state must contain a cookies array",
                code="authorized_session_state_invalid",
                status_code=422,
            )
        expires_at = config.get("session_expires_at")
        if not isinstance(expires_at, str) or not expires_at:
            raise PlatformCredentialError(
                "session_expires_at is required",
                code="authorized_session_expiry_required",
                status_code=422,
            )
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlatformCredentialError(
                "session_expires_at must be ISO 8601",
                code="authorized_session_expiry_invalid",
                status_code=422,
            ) from exc
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise PlatformCredentialError(
                "authorized session is already expired",
                code="authorized_session_expired",
                status_code=422,
            )

    @classmethod
    def _authorized_session_valid(cls, config: dict[str, Any]) -> bool:
        if not all(
            str(config.get(field, "")).casefold() == "true"
            for field in AUTHORIZED_SESSION_CONFIRMATIONS
        ):
            return False
        try:
            cls._validate_storage_state(config)
        except PlatformCredentialError:
            return False
        return True

    @staticmethod
    def _masked_config(config: dict[str, Any]) -> dict[str, Any]:
        safe = mask_secret_config(
            {
                key: value
                for key, value in config.items()
                if key
                not in {"username", "storage_state_json", "legacy_account_configs"}
            }
        )
        if config.get("username"):
            safe["username"] = "configured"
        if config.get("storage_state_json"):
            safe["storage_state_json"] = "configured"
        if config.get("legacy_account_configs"):
            safe["legacy_account_configs"] = "configured"
        if config.get("proxy_server"):
            safe["proxy_server"] = "configured"
        if config.get("proxy_username"):
            safe["proxy_username"] = "configured"
        if config.get("proxy_password"):
            safe["proxy_password"] = "configured"  # noqa: S105
        return safe

    def _audit(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        changes: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEntry(
                id=uuid4(),
                workspace_id=workspace_id,
                actor_type="user",
                actor_id=actor_id,
                action=action,
                resource_type="platform_credential_setting",
                resource_id=resource_id,
                before_hash=None,
                after_hash=None,
                change_summary_json=changes,
                reason=None,
                ip_hash=None,
                trace_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
