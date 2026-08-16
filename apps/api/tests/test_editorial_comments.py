"""Integration coverage for the editorial collaboration thread."""

import asyncio
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.services.generation as generation_module
from app.core.config import Settings
from app.db.session import create_engine_and_session
from app.models.workspace import WorkspaceMembership
from app.providers.llm.registry import build_llm_provider_registry
from app.services.generation import GenerationService
from app.services.generation_seed import seed_generation_defaults

from .conftest import PG_ASYNC_URL, TEST_PASSWORD, TEST_REDIS_URL, StubLLMProvider

RULE_SOURCE = (
    Path(__file__).parents[3]
    / "data"
    / "rules"
    / "ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_"
    "REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"
)


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-generation-secret",
        session_cookie_secure=False,
        cors_origins=["http://testserver"],
    )


def _authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def _import_rules(client: TestClient, csrf: str) -> None:
    response = client.post(
        "/api/v1/rules/import",
        headers={"X-CSRF-Token": csrf},
        json={
            "format": "txt",
            "filename": RULE_SOURCE.name,
            "content": RULE_SOURCE.read_text(encoding="utf-8"),
            "publish": True,
        },
    )
    assert response.status_code == 201, response.text


async def _seed_defaults() -> None:
    engine, session_factory = create_engine_and_session(_settings())
    try:
        async with session_factory() as session:
            membership = await session.scalar(select(WorkspaceMembership))
            assert membership is not None
            await seed_generation_defaults(session, membership.workspace_id, membership.user_id)
    finally:
        await engine.dispose()


async def _execute(run_id: UUID) -> None:
    engine, session_factory = create_engine_and_session(_settings())
    providers = build_llm_provider_registry(_settings())
    providers.replace(StubLLMProvider(key="openai_compatible"))
    try:
        async with session_factory() as session:
            await GenerationService(session, providers).execute_run(run_id)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


def test_editorial_comments_are_workspace_scoped_and_auditable(
    client: TestClient, monkeypatch
) -> None:
    csrf = _authenticate(client)
    _import_rules(client, csrf)
    asyncio.run(_seed_defaults())
    client.app.state.llm_providers.replace(StubLLMProvider(key="openai_compatible"))
    monkeypatch.setattr(generation_module, "enqueue_generation", lambda _run_id: None)

    workflow = client.get("/api/v1/workflows").json()[0]
    payload = {
        "workflow_id": workflow["id"],
        "input_type": "user_text",
        "input_payload": {
            "title": "协作评论测试事件",
            "text": "这是一段用于协作评论契约测试的已导入体育事件说明。",
        },
        "provider": "openai_compatible",
        "model": "stub-sports-writer-v1",
        "model_config": {"target_min_chars": 200, "target_max_chars": 220, "max_rewrites": 1},
    }
    created = client.post(
        "/api/v1/generations",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "editorial-comments-test"},
        json=payload,
    )
    assert created.status_code == 202, created.text
    run_id = UUID(created.json()["id"])
    asyncio.run(_execute(run_id))

    editorial = client.post(
        "/api/v1/editorial-items",
        headers={"X-CSRF-Token": csrf},
        json={"generation_run_id": str(run_id), "priority": 80},
    )
    assert editorial.status_code == 201, editorial.text
    item_id = editorial.json()["id"]

    empty = client.get(f"/api/v1/editorial-items/{item_id}/comments")
    assert empty.status_code == 200
    assert empty.json() == []

    missing_csrf = client.post(
        f"/api/v1/editorial-items/{item_id}/comments", json={"body": "缺少 CSRF"}
    )
    assert missing_csrf.status_code == 403

    blank = client.post(
        f"/api/v1/editorial-items/{item_id}/comments",
        headers={"X-CSRF-Token": csrf},
        json={"body": "   "},
    )
    assert blank.status_code == 422

    created_comment = client.post(
        f"/api/v1/editorial-items/{item_id}/comments",
        headers={"X-CSRF-Token": csrf},
        json={"body": "请核对第二段的来源时间，并补充官方链接。"},
    )
    assert created_comment.status_code == 201, created_comment.text
    comment = created_comment.json()
    assert comment["body"].startswith("请核对")
    assert comment["resolved_at"] is None

    resolved = client.patch(
        f"/api/v1/editorial-items/{item_id}/comments/{comment['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"resolved": True},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["resolved_at"] is not None

    comments = client.get(f"/api/v1/editorial-items/{item_id}/comments")
    assert comments.status_code == 200
    assert len(comments.json()) == 1
    assert comments.json()[0]["body"] == comment["body"]

    audits = client.get("/api/v1/operations/audits?action=editorial_comment")
    assert audits.status_code == 200, audits.text
    actions = {entry["action"] for entry in audits.json()["items"]}
    assert {"editorial_comment.created", "editorial_comment.resolution_changed"} <= actions
