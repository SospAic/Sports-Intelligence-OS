import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.adapters.platforms.registry import build_platform_adapter_registry
from app.core.config import Settings
from app.providers.llm.registry import build_llm_provider_registry
from app.providers.notifications.base import NotificationReceipt
from app.providers.notifications.http import GenericWebhookProvider
from app.providers.notifications.registry import build_notification_provider_registry
from app.services.automation import AutomationService
from app.services.generation_seed import seed_generation_defaults
from app.services.sync import PlatformSyncExecutor

from .conftest import (
    TEST_PASSWORD,
    TEST_PLATFORM_ID,
    RealShapedTestAdapter,
    StubLLMProvider,
)

RULE_SOURCE = (
    Path(__file__).parents[3]
    / "data"
    / "rules"
    / "ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_"
    "REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"
)
TEST_SECRET = "test-only-secret-not-used-in-production"  # noqa: S105 - test fixture


def _settings(database_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"postgresql+asyncpg://sio:sio-local-development-only@127.0.0.1:5432/{database_path}",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key=TEST_SECRET,
        session_cookie_secure=False,
        cors_origins=["http://testserver"],
        sync_page_limit=2,
    )


def _authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


async def _execute_sync(
    database_path: Path, run_id: UUID, adapter: PlatformSyncExecutor | None = None
) -> None:
    settings = _settings(database_path)
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = build_platform_adapter_registry(settings)
    if adapter is not None:
        # Drive the sync with a real-shaped, test-local adapter (source_kind='live').
        registry.replace(adapter)
    try:
        async with session_factory() as session:
            await PlatformSyncExecutor(session, registry, settings).execute_account_run(run_id)
    finally:
        for provider in registry.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


async def _seed_generation(database_path: Path) -> None:
    settings = _settings(database_path)
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            from app.models.workspace import WorkspaceMembership

            membership = await session.scalar(select(WorkspaceMembership))
            assert membership is not None
            await seed_generation_defaults(session, membership.workspace_id, membership.user_id)
    finally:
        await engine.dispose()


async def _send_delivery(database_path: Path, delivery_id: UUID) -> str:
    settings = _settings(database_path)
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    notifications = build_notification_provider_registry(settings)
    llms = build_llm_provider_registry(settings)
    try:
        async with session_factory() as session:
            delivered = await AutomationService(
                session, settings, notifications, llms
            ).send_delivery(delivery_id)
            return delivered.status
    finally:
        for registry in (notifications, llms):
            for provider in registry.values():
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
        await engine.dispose()


@pytest.mark.integration
def test_real_shaped_vertical_slice_keeps_every_step_auditable(
    client: TestClient,
    database_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实形状（source_kind='live'）账号同步 → 选题 → 生成 → 通知回执的完整首期链路，
    不进行任何外部网络调用；证明真实数据链路下每一步都可审计，且不伪造成功。"""

    monkeypatch.setattr("app.services.sync.enqueue_platform_sync", lambda _run_id: None)
    # Real LLM stub (source_kind='live') for the synchronous generation execution.
    # Registered under the real key so the request schema stays honest.
    client.app.state.llm_providers.replace(StubLLMProvider(key="openai_compatible"))

    # Stub the webhook provider's I/O offline so delivery runs without faking provenance.
    async def fake_send(self, config, message, *, idempotency_key):  # noqa: ANN001
        del config, message, idempotency_key
        return NotificationReceipt(status="delivered", external_id="stub-webhook-1")

    monkeypatch.setattr(GenericWebhookProvider, "send", fake_send)

    csrf = _authenticate(client)
    headers = {"X-CSRF-Token": csrf}

    # Deterministic, real-shaped adapter driving the account sync. The two syncs
    # differ only by ``view_offset`` so a 125_000 view delta (and thus
    # ``view_growth_1h``) is produced honestly from real-shaped data.
    adapter = RealShapedTestAdapter(key="youtube_browser", content_count=12)

    account_response = client.post(
        "/api/v1/accounts",
        headers=headers,
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": "e2e-account",
            "display_name": "E2E 测试创作者",
            "metadata": {"e2e": True},
        },
    )
    assert account_response.status_code == 201, account_response.text
    account = account_response.json()

    first_sync = client.post(f"/api/v1/accounts/{account['id']}/sync", headers=headers)
    assert first_sync.status_code == 202
    historical_time = datetime.now(UTC) - timedelta(hours=1)

    class HistoricalDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return historical_time

    adapter._view_offset = 0
    monkeypatch.setattr("app.services.sync.datetime", HistoricalDateTime)
    asyncio.run(_execute_sync(database_path, UUID(first_sync.json()["id"]), adapter))
    monkeypatch.setattr("app.services.sync.datetime", datetime)

    configured = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers=headers,
        json={"metadata": {"e2e": True, "snapshot_index": 5}},
    )
    assert configured.status_code == 200, configured.text
    second_sync = client.post(f"/api/v1/accounts/{account['id']}/sync", headers=headers)
    assert second_sync.status_code == 202
    adapter._view_offset = 125_000
    asyncio.run(_execute_sync(database_path, UUID(second_sync.json()["id"]), adapter))

    contents = client.get(f"/api/v1/accounts/{account['id']}/contents").json()
    assert contents["total"] == 12
    content = contents["items"][0]
    snapshots = client.get(f"/api/v1/contents/{content['id']}/snapshots").json()
    assert len(snapshots["items"]) == 2
    metrics = client.get(f"/api/v1/contents/{content['id']}/metrics").json()["items"]
    growth = next(item for item in metrics if item["metric_key"] == "view_growth_1h")
    assert growth["value"] == 125_000
    assert content["source_kind"] == "live"

    imported = client.post(
        "/api/v1/rules/import",
        headers=headers,
        json={
            "format": "txt",
            "filename": RULE_SOURCE.name,
            "content": RULE_SOURCE.read_text(encoding="utf-8"),
            "publish": True,
        },
    )
    assert imported.status_code == 201, imported.text
    asyncio.run(_seed_generation(database_path))
    workflow = client.get("/api/v1/workflows").json()[0]

    channel = client.post(
        "/api/v1/notification-channels",
        headers=headers,
        json={
            "provider_key": "generic_webhook",
            "name": "E2E Webhook（测试）",
            "config": {"url": "https://hooks.example.test/e2e"},
            "enabled": True,
        },
    ).json()
    rule_response = client.post(
        "/api/v1/automations",
        headers=headers,
        json={
            "name": "一小时增长内容包",
            "entity_type": "content",
            "trigger_type": "entity_updated",
            "condition_tree": {
                "field": "view_growth_1h",
                "operator": "gte",
                "value": 100_000,
            },
            "cooldown_seconds": 3600,
            "deduplication_window": 3600,
            "enabled": True,
            "actions": [
                {"action_type": "create_topic", "sort_order": 0, "config": {}},
                {
                    "action_type": "create_generation",
                    "sort_order": 1,
                    "config": {
                        "workflow_id": workflow["id"],
                        "provider": "openai_compatible",
                        "model": "stub-sports-writer-v1",
                        "model_config": {
                            "target_min_chars": 200,
                            "target_max_chars": 220,
                            "max_rewrites": 1,
                        },
                    },
                },
                {
                    "action_type": "webhook",
                    "sort_order": 2,
                    "config": {
                        "channel_id": channel["id"],
                        "title": "Growth alert",
                        "body": "Growth {view_growth_1h}; {generation_summary}",
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
            "entity_id": content["id"],
            "facts": {
                "entity_id": content["id"],
                "view_growth_1h": growth["value"],
                "source_kind": "live",
            },
            "event_key": "first-delivery-live-growth",
            "source_kind": "live",
            "test_mode": True,
        },
    )
    assert evaluation_response.status_code == 200, evaluation_response.text
    evaluation = evaluation_response.json()[0]
    actions = evaluation["condition_result"]["actions"]
    assert evaluation["matched"] is True
    assert [item["status"] for item in actions] == [
        "completed",
        "completed",
        "queued",
    ], actions
    assert evaluation["execution_status"] == "completed", evaluation
    generation_id = actions[1]["generation_id"]
    delivery_id = actions[2]["delivery_id"]

    generation = client.get(f"/api/v1/generations/{generation_id}").json()
    assert generation["status"] == "completed"
    assert generation["final_output"]["source_kind"] == "live"
    assert generation["final_output"]["tts_en"].startswith("STUB LLM OUTPUT")
    assert len(generation["steps"]) == 10
    topics = client.get("/api/v1/topics", params={"source_type": "content"}).json()
    assert topics["total"] == 1
    assert topics["items"][0]["source_id"] == content["id"]

    assert asyncio.run(_send_delivery(database_path, UUID(delivery_id))) == "delivered"
    deliveries = client.get("/api/v1/notification-deliveries").json()
    assert deliveries["items"][0]["status"] == "delivered"
    assert deliveries["items"][0]["provider_message_id"] == "stub-webhook-1"
    assert deliveries["items"][0]["payload"]["data"]["generation_id"] == generation_id
    evaluations = client.get(
        "/api/v1/automation-evaluations",
        params={"rule_id": rule_response.json()["id"]},
    ).json()
    assert evaluations["total"] == 1
    sync_runs = client.get(f"/api/v1/accounts/{account['id']}/sync-runs").json()
    assert [item["status"] for item in sync_runs["items"]] == ["success", "success"]
