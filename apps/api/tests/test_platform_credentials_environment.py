from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.services.platform_credentials import PlatformCredentialService


def _service(settings: Settings) -> PlatformCredentialService:
    # _environment_api_config and _read are pure with no database access when
    # no workspace row is supplied. Keeping this test at the service boundary
    # protects the environment-to-adapter contract without persisting secrets.
    service = object.__new__(PlatformCredentialService)
    service.settings = settings
    return service


def test_environment_api_credentials_are_available_for_supported_adapters() -> None:
    service = _service(
        Settings(
            _env_file=None,
            environment="test",
            youtube_api_key=SecretStr("youtube-key"),
            tiktok_client_key="tiktok-client",
            tiktok_client_secret=SecretStr("tiktok-secret"),
            tiktok_access_token=SecretStr("tiktok-access"),
            tiktok_refresh_token=SecretStr("tiktok-refresh"),
            douyin_client_key="douyin-client",
            douyin_client_secret=SecretStr("douyin-secret"),
            douyin_access_token=SecretStr("douyin-access"),
        )
    )

    youtube = service._environment_api_config("youtube")
    tiktok = service._environment_api_config("tiktok")
    douyin = service._environment_api_config("douyin")

    assert youtube == {"api_key": "youtube-key"}
    assert tiktok["client_key"] == "tiktok-client"
    assert tiktok["refresh_token"].endswith("refresh")
    assert douyin == {
        "client_key": "douyin-client",
        "client_secret": "douyin-secret",
        "access_token": "douyin-access",
    }


def test_empty_or_incomplete_environment_credentials_are_not_reported_as_configured() -> None:
    service = _service(
        Settings(
            _env_file=None,
            environment="test",
            youtube_api_key=SecretStr(""),
            tiktok_client_key="client-only",
            tiktok_client_secret=SecretStr(""),
            tiktok_access_token=SecretStr(""),
            tiktok_refresh_token=SecretStr(""),
        )
    )

    assert service._environment_api_config("youtube") == {}
    assert service._environment_api_config("tiktok") == {"client_key": "client-only"}
    assert service._read("youtube", None).configured is False
    assert service._read("tiktok", None).configured is False


@pytest.mark.asyncio
async def test_api_resolution_uses_environment_key_when_workspace_uses_browser_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(
        Settings(_env_file=None, environment="test", youtube_api_key=SecretStr("youtube-key"))
    )
    row = SimpleNamespace(mode="authorized_session", enabled=True)

    async def fake_row(workspace_id, platform_key):  # noqa: ANN001
        return row

    monkeypatch.setattr(service, "_row", fake_row)
    mode, config = await service.resolve_api(uuid4(), "youtube")

    assert mode == "api"
    assert config == {"api_key": "youtube-key"}


@pytest.mark.asyncio
async def test_disabled_workspace_api_row_blocks_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(
        Settings(_env_file=None, environment="test", youtube_api_key=SecretStr("youtube-key"))
    )
    row = SimpleNamespace(mode="api", enabled=False, config_encrypted="encrypted")

    async def fake_row(workspace_id, platform_key):  # noqa: ANN001
        return row

    monkeypatch.setattr(service, "_row", fake_row)
    service.cipher = SimpleNamespace(decrypt=lambda _: {})
    mode, config = await service.resolve_api(uuid4(), "youtube")

    assert mode == "unconfigured"
    assert config == {}
