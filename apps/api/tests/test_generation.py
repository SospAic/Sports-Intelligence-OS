import asyncio
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select

import app.services.generation as generation_module
from app.core.config import Settings
from app.db.session import create_engine_and_session
from app.models.workspace import WorkspaceMembership
from app.prompts.renderer import PromptRenderError, redact_sensitive, render_prompt
from app.providers.llm.base import LLMMessage, LLMRequest, LLMResponse
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.registry import build_llm_provider_registry
from app.services.generation import GenerationService
from app.services.generation_seed import seed_generation_defaults
from app.workflows.generation import deterministic_qa

from .conftest import TEST_PASSWORD

RULE_SOURCE = (
    Path(__file__).parents[3]
    / "data"
    / "rules"
    / "ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_"
    "REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"
)


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def import_rules(client: TestClient, csrf: str) -> None:
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


def test_prompt_renderer_is_strict_and_redacts_sensitive_fields() -> None:
    schema = {
        "type": "object",
        "required": ["facts"],
        "properties": {"facts": {"type": "array"}},
        "additionalProperties": False,
    }
    rendered = render_prompt("Facts: {{facts}}", schema, {"facts": ["A"]})
    assert rendered == 'Facts: ["A"]'
    try:
        render_prompt("Facts: {{facts}}", schema, {"facts": [], "api_key": "secret"})
    except PromptRenderError as exc:
        assert "Unknown prompt variables" in str(exc)
    else:
        raise AssertionError("strict prompt rendering must reject unknown variables")
    assert redact_sensitive({"api_key": "secret", "nested": {"token": "secret"}}) == {
        "api_key": "***REDACTED***",
        "nested": {"token": "***REDACTED***"},
    }


def test_mock_llm_output_is_reproducible_and_explicitly_labelled() -> None:
    async def generate() -> tuple[LLMResponse, LLMResponse]:
        provider = MockLLMProvider()
        request = LLMRequest(
            model="mock-sports-writer-v1",
            messages=(LLMMessage(role="user", content="test"),),
            parameters={"target_min_chars": 200, "target_max_chars": 220},
            response_schema=None,
            timeout_seconds=5,
            idempotency_key="stable",
            metadata={"title": "test event", "step_key": "generate_draft"},
        )
        first = await provider.generate(request)
        second = await provider.generate(request)
        return first, second

    first, second = asyncio.run(generate())
    assert first.content == second.content
    assert isinstance(first.content, str)
    assert first.content.startswith("MOCK TEST OUTPUT")
    assert first.provider_metadata["source_kind"] == "mock"
    assert 200 <= len(first.content) <= 220


def test_deterministic_qa_detects_early_or_missing_answer_words() -> None:
    early = deterministic_qa(
        "The winner was Jordan, after a long sequence that finally explained the result.",
        target_min_chars=1,
        target_max_chars=500,
        verification_status="corroborated",
        protected_answer_words=["Jordan"],
        answer_reveal_min_ratio=0.55,
    )
    assert early["valid"] is False
    assert early["answer_protection"]["checks"][0]["status"] == "revealed_too_early"
    assert any(
        item["code"] == "protected_answer_word_revealed_too_early" for item in early["findings"]
    )

    missing = deterministic_qa(
        "The sequence ends without identifying the athlete.",
        target_min_chars=1,
        target_max_chars=500,
        verification_status="corroborated",
        protected_answer_words=["Jordan"],
    )
    assert missing["answer_protection"]["checks"][0]["status"] == "missing"


async def _seed_defaults(database_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-generation-secret",
        session_cookie_secure=False,
        cors_origins=["http://testserver"],
    )
    engine, session_factory = create_engine_and_session(settings)
    try:
        async with session_factory() as session:
            membership = await session.scalar(select(WorkspaceMembership))
            assert membership is not None
            await seed_generation_defaults(session, membership.workspace_id, membership.user_id)
    finally:
        await engine.dispose()


async def _execute(database_path: Path, run_id: UUID) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        redis_url="redis://127.0.0.1:6399/15",
        secret_key="test-only-generation-secret",
        session_cookie_secure=False,
        cors_origins=["http://testserver"],
    )
    engine, session_factory = create_engine_and_session(settings)
    providers = build_llm_provider_registry(settings)
    try:
        async with session_factory() as session:
            await GenerationService(session, providers).execute_run(run_id)
    finally:
        for provider in providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        await engine.dispose()


def test_generation_api_runs_ten_step_mock_workflow_without_fake_verification(
    client: TestClient, database_path: Path, monkeypatch: MonkeyPatch
) -> None:
    csrf = authenticate(client)
    import_rules(client, csrf)
    asyncio.run(_seed_defaults(database_path))
    monkeypatch.setattr(generation_module, "enqueue_generation", lambda _run_id: None)

    workflows = client.get("/api/v1/workflows")
    assert workflows.status_code == 200
    workflow = workflows.json()[0]
    assert workflow["name"] == "Sports Short Video Full Package"
    assert len(workflow["steps"]) == 10

    prompts = client.get("/api/v1/prompts")
    assert prompts.status_code == 200
    assert prompts.json()["items"][0]["current_version_id"]

    payload = {
        "workflow_id": workflow["id"],
        "input_type": "user_text",
        "input_payload": {
            "title": "测试体育事件",
            "text": "这是一段由用户导入、尚未经过独立联网核实的体育事件说明。",
        },
        "provider": "mock_llm",
        "model": "mock-sports-writer-v1",
        "model_config": {
            "target_min_chars": 200,
            "target_max_chars": 220,
            "max_rewrites": 1,
        },
    }
    preview = client.post(
        "/api/v1/generations/preview",
        headers={"X-CSRF-Token": csrf},
        json=payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["provider"]["api_key"] == "***BACKEND ONLY***"
    assert "Mock LLM" in " ".join(preview.json()["warnings"])

    created = client.post(
        "/api/v1/generations",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "generation-test-1"},
        json=payload,
    )
    assert created.status_code == 202, created.text
    run_id = UUID(created.json()["id"])
    assert created.json()["status"] == "queued"
    assert created.json()["metadata"]["source_kind"] == "mock"

    duplicate = client.post(
        "/api/v1/generations",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "generation-test-1"},
        json=payload,
    )
    assert duplicate.status_code == 202
    assert duplicate.json()["id"] == str(run_id)

    asyncio.run(_execute(database_path, run_id))
    detail = client.get(f"/api/v1/generations/{run_id}")
    assert detail.status_code == 200, detail.text
    result = detail.json()
    assert result["status"] == "completed"
    assert result["verification_status"] == "verification_incomplete"
    assert len(result["steps"]) == 10
    assert all(step["status"] == "completed" for step in result["steps"])
    assert result["final_output"]["source_kind"] == "mock"
    assert result["final_output"]["tts_en"].startswith("MOCK TEST OUTPUT")
    assert 200 <= len(result["final_output"]["tts_en"]) <= 220
    assert result["validation_result"]["valid"] is True
    assert result["validation_result"]["warnings"] == 1
    assert result["rewrite_count"] <= payload["model_config"]["max_rewrites"]
    assert result["token_usage"]["total_tokens"] > 0
    assert Decimal(str(result["estimated_cost"])) == 0

    text_export = client.get(f"/api/v1/generations/{run_id}/export", params={"format": "txt"})
    assert text_export.status_code == 200
    assert "英文 TTS" in text_export.text
    json_export = client.get(f"/api/v1/generations/{run_id}/export", params={"format": "json"})
    assert json_export.status_code == 200
    assert json_export.json()["id"] == str(run_id)


def test_generation_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/prompts").status_code == 401
    assert client.get("/api/v1/workflows").status_code == 401
    assert client.get("/api/v1/generations").status_code == 401
