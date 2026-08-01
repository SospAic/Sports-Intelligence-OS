import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.automations.conditions import (
    ConditionValidationError,
    evaluate_condition_tree,
    validate_condition_tree,
)
from app.core.config import Settings
from app.models.automation import NotificationChannel
from app.providers.notifications.base import NotificationMessage, NotificationReceipt
from app.providers.notifications.crypto import NotificationConfigCipher, mask_notification_config
from app.providers.notifications.http import (
    DingTalkProvider,
    DiscordProvider,
    FeishuProvider,
    GenericWebhookProvider,
    TelegramProvider,
    WeComProvider,
)
from app.providers.notifications.registry import build_notification_provider_registry

from .conftest import TEST_PASSWORD


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_condition_tree_validation_and_three_valued_evaluation() -> None:
    tree = {
        "operator": "AND",
        "conditions": [
            {"field": "view_count", "operator": "gte", "value": 1_000_000},
            {"field": "view_growth_1h", "operator": "gte", "value": 100_000},
        ],
    }
    validate_condition_tree(tree, "content")
    matched = evaluate_condition_tree(tree, {"view_count": 1_500_000, "view_growth_1h": 120_000})
    assert matched.matched is True
    missing = evaluate_condition_tree(tree, {"view_count": 1_500_000})
    assert missing.value is None
    assert missing.matched is False

    selected_id = str(uuid4())
    selected_tree = {
        "field": "entity_id",
        "operator": "in",
        "value": [selected_id],
    }
    validate_condition_tree(selected_tree, "content")
    assert evaluate_condition_tree(selected_tree, {"entity_id": selected_id}).matched is True

    with pytest.raises(ConditionValidationError, match="high-risk"):
        validate_condition_tree(
            {"field": "title", "operator": "regex", "value": "(a+)+$"},
            "content",
        )

    try:
        validate_condition_tree(
            {"field": "unknown_secret", "operator": "eq", "value": "x"}, "content"
        )
    except ConditionValidationError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("unknown fields must be rejected")


def test_notification_config_encryption_masking_and_provider_contracts() -> None:
    config = {
        "url": "https://example.com/hooks/secret-token",
        "signing_secret": "super-secret",
        "headers": {"Authorization": "Bearer secret"},
    }
    cipher = NotificationConfigCipher("test-encryption-material-at-least-32-characters")
    encrypted = cipher.encrypt(config)
    assert "super-secret" not in encrypted
    assert cipher.decrypt(encrypted) == config
    masked = mask_notification_config(config)
    assert masked["signing_secret"] == "••••••••"  # noqa: S105 - masked sentinel
    assert "secret-token" not in str(masked["url"])
    assert "Bearer secret" not in str(masked)

    settings = Settings(environment="test", secret_key="test-notification-registry-secret")
    registry = build_notification_provider_registry(settings)
    assert set(registry.keys()) == {
        "email",
        "generic_webhook",
        "telegram",
        "discord",
        "feishu",
        "dingtalk",
        "wecom",
    }

    async def close() -> None:
        for provider in registry.values():
            closer = getattr(provider, "aclose", None)
            if closer is not None:
                await closer()

    asyncio.run(close())


def test_http_notification_providers_emit_channel_specific_payloads(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, object], dict[str, str]]] = []

    async def allow_test_endpoint(url: str, *, allow_secret_query: bool = False) -> str:
        del allow_secret_query
        return url

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        captured.append((str(request.url), body, dict(request.headers)))
        if "telegram" in request.url.host:
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})
        if "discord" in request.url.host:
            return httpx.Response(204)
        return httpx.Response(200, json={"errcode": 0})

    monkeypatch.setattr(
        "app.providers.notifications.http.ensure_public_endpoint", allow_test_endpoint
    )

    async def send_all() -> None:
        message = NotificationMessage(title="标题", body="正文", url="https://sio.example/item")
        providers_and_configs = [
            (
                GenericWebhookProvider(timeout_seconds=1, max_attempts=1),
                {"url": "https://hooks.example/notify", "signing_secret": "test-signing"},
            ),
            (
                TelegramProvider(timeout_seconds=1, max_attempts=1),
                {"bot_token": "test-token", "chat_id": "123"},
            ),
            (
                DiscordProvider(timeout_seconds=1, max_attempts=1),
                {"webhook_url": "https://discord.example/hook"},
            ),
            (
                FeishuProvider(timeout_seconds=1, max_attempts=1),
                {"webhook_url": "https://feishu.example/hook", "secret": "test-secret"},
            ),
            (
                DingTalkProvider(timeout_seconds=1, max_attempts=1),
                {"webhook_url": "https://dingtalk.example/hook", "secret": "test-secret"},
            ),
            (
                WeComProvider(timeout_seconds=1, max_attempts=1),
                {"webhook_url": "https://wecom.example/hook"},
            ),
        ]
        for provider, config in providers_and_configs:
            await provider._client.aclose()  # noqa: SLF001 - controlled provider contract test
            provider._client = httpx.AsyncClient(  # noqa: SLF001
                transport=httpx.MockTransport(handler)
            )
            await provider.send(config, message, idempotency_key=f"test-{provider.key}")
            await provider.aclose()

    asyncio.run(send_all())
    assert len(captured) == 6
    generic = captured[0]
    assert generic[1]["title"] == "标题"
    assert generic[2]["x-sio-signature-sha256"]
    assert captured[1][1]["chat_id"] == "123"
    assert captured[2][1]["content"].startswith("标题")
    assert captured[3][1]["msg_type"] == "text"
    assert captured[3][1]["sign"]
    assert "timestamp=" in captured[4][0] and "sign=" in captured[4][0]
    assert captured[5][1]["msgtype"] == "text"


def test_automation_api_cooldown_dedup_and_delivery(
    client: TestClient, monkeypatch: MonkeyPatch
) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}

    provider_response = client.get("/api/v1/notification-providers")
    assert provider_response.status_code == 200
    assert {item["key"] for item in provider_response.json()} >= {
        "email",
        "generic_webhook",
        "telegram",
        "discord",
        "feishu",
        "dingtalk",
        "wecom",
    }
    providers = {item["key"]: item for item in provider_response.json()}
    email_fields = {item["key"] for item in providers["email"]["config_fields"]}
    webhook_fields = {item["key"] for item in providers["generic_webhook"]["config_fields"]}
    assert {"host", "port", "use_tls", "use_ssl", "timeout_seconds"} <= email_fields
    assert {"url", "headers", "signing_secret", "max_attempts"} <= webhook_fields

    # The test-delivery endpoint performs a real send. Stub the provider's I/O
    # so the test runs offline without faking any data provenance.
    async def fake_send(self, config, message, *, idempotency_key):  # noqa: ANN001
        del config, message, idempotency_key
        return NotificationReceipt(status="delivered", external_id="stub-test-1")

    monkeypatch.setattr(GenericWebhookProvider, "send", fake_send)

    channel_response = client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "provider_key": "generic_webhook",
            "name": "仅测试 Webhook 渠道",
            "config": {"url": "https://hooks.example.test/notify"},
            "enabled": True,
        },
    )
    assert channel_response.status_code == 201, channel_response.text
    channel = channel_response.json()
    assert "config_encrypted" not in channel
    assert "config" not in channel

    rule_response = client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "测试百万播放通知",
            "entity_type": "content",
            "trigger_type": "entity_updated",
            "condition_tree": {
                "field": "view_count",
                "operator": "gte",
                "value": 1_000_000,
            },
            "schedule": {},
            "cooldown_seconds": 3600,
            "deduplication_window": 3600,
            "enabled": True,
            "actions": [
                {
                    "action_type": "notification",
                    "sort_order": 0,
                    "config": {
                        "channel_id": channel["id"],
                        "title": "百万播放提醒",
                        "body": "作品达到 {view_count} 播放。",
                    },
                }
            ],
        },
    )
    assert rule_response.status_code == 201, rule_response.text
    rule_id = rule_response.json()["id"]

    entity_id = str(uuid4())
    live = client.post(
        "/api/v1/automations/evaluate",
        headers=headers,
        json={
            "entity_type": "content",
            "entity_id": entity_id,
            "facts": {"view_count": 1_200_000},
            "event_key": "live-event-one",
            "source_kind": "live",
        },
    )
    assert live.status_code == 200, live.text
    evaluation = live.json()[0]
    assert evaluation["rule_id"] == rule_id
    assert evaluation["matched"] is True
    assert evaluation["execution_status"] == "completed"
    assert evaluation["condition_result"]["actions"][0]["status"] == "queued"

    repeated = client.post(
        "/api/v1/automations/evaluate",
        headers=headers,
        json={
            "entity_type": "content",
            "entity_id": entity_id,
            "facts": {"view_count": 1_300_000},
            "event_key": "live-event-two",
            "source_kind": "live",
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()[0]["execution_status"] == "suppressed"
    assert repeated.json()[0]["condition_result"]["suppression"] == "cooldown_active"

    deliveries = client.get("/api/v1/notification-deliveries")
    assert deliveries.status_code == 200
    assert deliveries.json()["total"] == 1
    assert deliveries.json()["items"][0]["payload"]["data"]["source_kind"] == "live"

    test_delivery = client.post(
        f"/api/v1/notification-channels/{channel['id']}/test",
        headers=headers,
        json={"title": "测试通知", "body": "仅验证 Webhook 通知契约"},
    )
    assert test_delivery.status_code == 200, test_delivery.text
    assert test_delivery.json()["status"] == "delivered"
    assert test_delivery.json()["provider_message_id"] == "stub-test-1"


def test_automation_notification_uses_published_template(client: TestClient) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}
    template = client.post(
        "/api/v1/notification-templates",
        headers=headers,
        json={
            "name": "Published automation template",
            "description": "Template integration test",
            "category": "automation",
            "subject_template": "{rule_name}: {view_count}",
            "body_template": "Entity {entity_id} reached {view_count}",
            "variables_schema": {},
        },
    )
    assert template.status_code == 201, template.text
    template_id = template.json()["id"]

    before_publish = client.get("/api/v1/notification-templates")
    assert before_publish.status_code == 200
    assert before_publish.json()["items"][0]["published_version"] is None
    published = client.post(
        f"/api/v1/notification-templates/{template_id}/publish",
        headers=headers,
        json={},
    )
    assert published.status_code == 200, published.text

    channel = client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "provider_key": "generic_webhook",
            "name": "Template test channel",
            "config": {"url": "https://hooks.example.test/template"},
            "enabled": True,
        },
    )
    assert channel.status_code == 201, channel.text
    rule = client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "Template rule",
            "entity_type": "content",
            "trigger_type": "entity_updated",
            "condition_tree": {"field": "view_count", "operator": "gte", "value": 1},
            "schedule": {},
            "cooldown_seconds": 0,
            "deduplication_window": 0,
            "enabled": True,
            "actions": [
                {
                    "action_type": "notification",
                    "sort_order": 0,
                    "config": {
                        "channel_id": channel.json()["id"],
                        "template_id": template_id,
                    },
                }
            ],
        },
    )
    assert rule.status_code == 201, rule.text
    entity_id = str(uuid4())
    evaluated = client.post(
        "/api/v1/automations/evaluate",
        headers=headers,
        json={
            "entity_type": "content",
            "entity_id": entity_id,
            "facts": {"view_count": 42},
            "event_key": "published-template-test",
            "source_kind": "live",
        },
    )
    assert evaluated.status_code == 200, evaluated.text
    deliveries = client.get("/api/v1/notification-deliveries")
    assert deliveries.status_code == 200
    payload = deliveries.json()["items"][0]["payload"]
    assert payload["title"] == "Template rule: 42"
    assert payload["body"] == f"Entity {entity_id} reached 42"
    assert payload["data"]["notification_template_id"] == template_id
    assert payload["data"]["notification_template_version"] == 1


def test_notification_channel_edit_preserves_blank_secrets(
    client: TestClient,
    database_path: Path,
) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}
    created = client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "provider_key": "generic_webhook",
            "name": "精细参数 Webhook",
            "config": {
                "url": "https://hooks.example.com/sports/private-token",
                "headers": {"Authorization": "Bearer private-value"},
                "signing_secret": "signing-secret-value",
                "timeout_seconds": 10,
                "max_attempts": 3,
            },
            "enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    channel_id = created.json()["id"]
    assert "private-token" not in created.text
    assert "private-value" not in created.text
    assert "signing-secret-value" not in created.text

    updated = client.patch(
        f"/api/v1/notification-channels/{channel_id}",
        headers=headers,
        json={
            "name": "精细参数 Webhook（更新）",
            "config": {"signing_secret": "", "timeout_seconds": 25, "max_attempts": 4},
        },
    )
    assert updated.status_code == 200, updated.text

    sync_engine = create_engine(f"sqlite:///{database_path}")
    try:
        with Session(sync_engine) as session:
            channel = session.scalar(
                select(NotificationChannel).where(NotificationChannel.id == UUID(channel_id))
            )
            assert channel is not None
            config = NotificationConfigCipher("test-only-secret-not-used-in-production").decrypt(
                channel.config_encrypted
            )
            assert config["signing_secret"] == "signing-secret-value"  # noqa: S105
            assert config["headers"]["Authorization"] == "Bearer private-value"
            assert config["timeout_seconds"] == 25
            assert config["max_attempts"] == 4
    finally:
        sync_engine.dispose()


def test_automation_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/automations").status_code == 401
    assert client.get("/api/v1/notification-channels").status_code == 401


def test_generation_failure_does_not_block_following_notification(
    client: TestClient, monkeypatch: MonkeyPatch
) -> None:
    csrf = authenticate(client)
    headers = {"X-CSRF-Token": csrf}
    channel_response = client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "provider_key": "generic_webhook",
            "name": "AI 失败降级测试渠道",
            "config": {"url": "https://hooks.example.test/ai-fallback"},
            "enabled": True,
        },
    )
    assert channel_response.status_code == 201
    channel_id = channel_response.json()["id"]

    # The notification action performs a real send. Stub the provider's I/O
    # offline so the test runs without faking any data provenance.
    async def fake_send(self, config, message, *, idempotency_key):  # noqa: ANN001
        del config, message, idempotency_key
        return NotificationReceipt(status="delivered", external_id="stub-fallback-1")

    monkeypatch.setattr(GenericWebhookProvider, "send", fake_send)

    rule_response = client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "AI 失败仍通知",
            "entity_type": "content",
            "condition_tree": {
                "field": "view_growth_1h",
                "operator": "gte",
                "value": 100_000,
            },
            "enabled": True,
            "actions": [
                {
                    "action_type": "create_generation",
                    "sort_order": 0,
                    "config": {
                        "workflow_id": str(uuid4()),
                        "provider": "unconfigured_llm",
                        "model": "nonexistent-model",
                    },
                },
                {
                    "action_type": "notification",
                    "sort_order": 1,
                    "config": {
                        "channel_id": channel_id,
                        "title": "原始提醒",
                        "body": "增长 {view_growth_1h}；生成状态：{generation_error}",
                    },
                },
            ],
        },
    )
    assert rule_response.status_code == 201, rule_response.text

    evaluation_response = client.post(
        "/api/v1/automations/evaluate",
        headers=headers,
        json={
            "entity_type": "content",
            "entity_id": str(uuid4()),
            "facts": {"view_growth_1h": 120_000},
            "event_key": "generation-failure-fallback",
            "source_kind": "live",
        },
    )
    assert evaluation_response.status_code == 200, evaluation_response.text
    evaluation = evaluation_response.json()[0]
    assert evaluation["execution_status"] == "partial"
    assert [item["status"] for item in evaluation["condition_result"]["actions"]] == [
        "failed",
        "queued",
    ]
    deliveries = client.get("/api/v1/notification-deliveries").json()
    assert deliveries["total"] == 1
    assert deliveries["items"][0]["payload"]["data"]["generation_error"]
