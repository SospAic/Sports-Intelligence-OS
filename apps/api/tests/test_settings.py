from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.settings import LLMProviderSetting, PlatformCredentialSetting

from .conftest import TEST_PASSWORD, PG_SYNC_URL


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_runtime_settings_are_detailed_but_do_not_expose_credentials(
    client: TestClient,
) -> None:
    authenticate(client)
    response = client.get("/api/v1/settings/runtime")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["apply_mode"] == "environment_restart"
    sections = {section["key"]: section for section in payload["sections"]}
    assert {"database", "redis", "tasks", "security"} <= set(sections)
    database_fields = {item["key"]: item for item in sections["database"]["fields"]}
    redis_fields = {item["key"]: item for item in sections["redis"]["fields"]}
    assert database_fields["database_pool_size"]["env_var"] == "SIO_DATABASE_POOL_SIZE"
    assert redis_fields["redis_max_connections"]["maximum"] == 1000
    serialized = response.text.casefold()
    assert "test-only-secret-not-used-in-production" not in serialized
    assert "password=" not in serialized


def test_workspace_llm_configuration_is_encrypted_masked_and_used_by_descriptors(
    client: TestClient,
    database_path: Path,
) -> None:
    csrf = authenticate(client)
    secret = "sk-test-provider-secret-never-returned"  # noqa: S105
    response = client.put(
        "/api/v1/settings/llm/openai-compatible",
        headers={"X-CSRF-Token": csrf},
        json={
            "name": "编辑工作区模型",
            "base_url": "https://llm.example.com/v1",
            "api_key": secret,
            "organization": "org-example",
            "project": "sports-project",
            "custom_headers": {"X-Tenant-ID": "tenant-secret-value"},
            "default_model": "sports-model-v2",
            "temperature": 0,
            "top_p": 0.85,
            "max_tokens": 8192,
            "timeout_seconds": 45,
            "max_attempts": 4,
            "input_cost_per_million": "0.25",
            "output_cost_per_million": "1.75",
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "database"
    assert body["configured"] is True
    assert body["api_key_configured"] is True
    assert body["default_parameters"] == {
        "temperature": 0.0,
        "top_p": 0.85,
        "max_tokens": 8192,
    }
    assert secret not in response.text
    assert "tenant-secret-value" not in response.text
    assert body["config_masked"]["api_key"] == "••••••••"
    assert body["config_masked"]["custom_headers"]["X-Tenant-ID"] == "••••••••"

    provider_response = client.get("/api/v1/llm/providers")
    assert provider_response.status_code == 200, provider_response.text
    descriptor = next(
        item for item in provider_response.json() if item["key"] == "openai_compatible"
    )
    assert descriptor["configured"] is True
    assert descriptor["source"] == "database"
    assert descriptor["default_model"] == "sports-model-v2"
    assert descriptor["default_parameters"]["temperature"] == 0.0

    sync_engine = create_engine(PG_SYNC_URL)
    try:
        with Session(sync_engine) as session:
            row = session.scalar(select(LLMProviderSetting))
            assert row is not None
            assert secret not in row.config_encrypted
            assert "tenant-secret-value" not in row.config_encrypted
            assert row.config_masked["api_key"] == "••••••••"
    finally:
        sync_engine.dispose()


def test_llm_update_preserves_blank_secret_and_can_clear_optional_values(
    client: TestClient,
) -> None:
    csrf = authenticate(client)
    base_payload = {
        "name": "兼容模型",
        "base_url": "https://llm.example.com/v1",
        "default_model": "model-a",
        "temperature": 0.4,
        "top_p": 1,
        "max_tokens": 4096,
        "timeout_seconds": 60,
        "max_attempts": 3,
        "enabled": True,
    }
    created = client.put(
        "/api/v1/settings/llm/openai-compatible",
        headers={"X-CSRF-Token": csrf},
        json={
            **base_payload,
            "api_key": "sk-preserved-secret",
            "organization": "org-to-clear",
        },
    )
    assert created.status_code == 200, created.text

    updated = client.put(
        "/api/v1/settings/llm/openai-compatible",
        headers={"X-CSRF-Token": csrf},
        json={**base_payload, "organization": None, "project": None},
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["api_key_configured"] is True
    assert "organization" not in payload["config_masked"]


def test_settings_write_requires_csrf(client: TestClient) -> None:
    authenticate(client)
    response = client.put(
        "/api/v1/settings/llm/openai-compatible",
        json={
            "base_url": "https://llm.example.com/v1",
            "default_model": "model-a",
        },
    )
    assert response.status_code == 403


def test_platform_acquisition_modes_are_encrypted_retained_and_revocable(
    client: TestClient, database_path: Path
) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}
    public_policy = {
        "terms_permission_confirmed": "true",
        "robots_reviewed": "true",
        "fields_minimized": "true",
        "source_audit_enabled": "true",
        "sample_interval_seconds": "300",
    }
    public_response = client.put(
        "/api/v1/settings/platform-credentials/test_platform",
        headers=headers,
        json={"mode": "public_page", "config": public_policy, "enabled": True},
    )
    assert public_response.status_code == 200, public_response.text
    assert public_response.json()["configured"] is True

    username = "owner@example.com"
    password = "encrypted-platform-password"  # noqa: S105
    login_response = client.put(
        "/api/v1/settings/platform-credentials/test_platform",
        headers=headers,
        json={
            "mode": "authorized_login",
            "config": {
                "username": username,
                "password": password,
                "account_authorization_confirmed": "true",
                "platform_login_allowed": "true",
                "oauth_unavailable_or_insufficient": "true",
            },
            "enabled": True,
        },
    )
    assert login_response.status_code == 200, login_response.text
    assert username not in login_response.text
    assert password not in login_response.text
    assert login_response.json()["config_masked"]["username"] == "configured"

    storage_state = '{"cookies":[{"name":"sid","value":"private"}],"origins":[]}'
    session_response = client.put(
        "/api/v1/settings/platform-credentials/test_platform",
        headers=headers,
        json={
            "mode": "authorized_session",
            "config": {
                "storage_state_json": storage_state,
                "session_label": "owned account",
                "session_expires_at": (
                    datetime.now(UTC) + timedelta(days=1)
                ).isoformat(),
                "account_authorization_confirmed": "true",
                "platform_session_allowed": "true",
                "oauth_unavailable_or_insufficient": "true",
            },
            "enabled": True,
        },
    )
    assert session_response.status_code == 200, session_response.text
    assert storage_state not in session_response.text
    assert session_response.json()["config_masked"]["storage_state_json"] == "configured"

    revoked = client.post(
        "/api/v1/settings/platform-credentials/test_platform/revoke-login",
        headers=headers,
        json={},
    )
    assert revoked.status_code == 200, revoked.text
    revoked_body = revoked.json()
    assert revoked_body["mode"] == "public_page"
    assert revoked_body["configured"] is True
    assert not {
        "username",
        "password",
        "storage_state_json",
    } & set(revoked_body["configured_fields"])

    sync_engine = create_engine(PG_SYNC_URL)
    try:
        with Session(sync_engine) as session:
            row = session.scalar(select(PlatformCredentialSetting))
            assert row is not None
            assert username not in row.config_encrypted
            assert password not in row.config_encrypted
            assert "private" not in row.config_encrypted
    finally:
        sync_engine.dispose()


def test_platform_adapters_expose_capability_matrix(client: TestClient) -> None:
    authenticate(client)
    response = client.get("/api/v1/settings/platform-adapters")
    assert response.status_code == 200, response.text
    adapters = response.json()
    assert isinstance(adapters, list)
    assert len(adapters) >= 1
    keys = {adapter["key"] for adapter in adapters}
    assert "youtube" in keys
    assert "mock_platform" not in keys
    for adapter in adapters:
        assert set(adapter) >= {
            "key",
            "name",
            "implementation_status",
            "capabilities",
            "config_fields",
            "source_kinds",
        }
        assert adapter["implementation_status"] in {"implemented", "skeleton"}
        assert isinstance(adapter["capabilities"], dict)
        assert all(
            isinstance(value, bool) for value in adapter["capabilities"].values()
        )
        assert isinstance(adapter["source_kinds"], list)
        for field in adapter["config_fields"]:
            assert set(field) >= {"key", "label", "required", "secret"}
