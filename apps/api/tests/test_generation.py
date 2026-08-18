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
from app.providers.llm.registry import build_llm_provider_registry
from app.services.generation import GenerationService
from app.services.generation_seed import seed_generation_defaults
from app.workflows.generation import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MIN_CHARS,
    deterministic_qa,
    validate_final_bundle,
)

from .conftest import PG_ASYNC_URL, TEST_PASSWORD, TEST_REDIS_URL, StubLLMProvider

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


def test_stub_llm_output_is_reproducible_and_labelled_live() -> None:
    async def generate() -> tuple[LLMResponse, LLMResponse]:
        provider = StubLLMProvider()
        request = LLMRequest(
            model="stub-sports-writer-v1",
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
    assert first.content.startswith("STUB LLM OUTPUT")
    assert first.provider_metadata["source_kind"] == "live"
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


def test_generation_freezes_only_bounded_creator_controls() -> None:
    controls = GenerationService._creator_controls(
        {
            "answer_word": "  Jordan  ",
            "answer_reveal_min_ratio": 2,
            "creator_brief": "Focus on the final possession.",
            "title": "must not override database facts",
        }
    )
    assert controls == {
        "answer_word": "Jordan",
        "answer_reveal_min_ratio": 0.9,
        "creator_brief": "Focus on the final possession.",
    }


def test_generation_freezes_selected_video_subtitles() -> None:
    context = GenerationService._video_context(
        {
            "video_context": {
                "name": "A tracked video",
                "subtitleLangs": ["en"],
                "subtitles": [{"lang": "en", "text": "First verified line"}],
            }
        }
    )
    assert context == {
        "name": "A tracked video",
        "subtitle_langs": ["en"],
        "subtitles": [{"lang": "en", "text": "First verified line"}],
    }


async def _seed_defaults(database_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
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
        database_url=PG_ASYNC_URL,
        redis_url=TEST_REDIS_URL,
        secret_key="test-only-generation-secret",
        session_cookie_secure=False,
        cors_origins=["http://testserver"],
    )
    engine, session_factory = create_engine_and_session(settings)
    providers = build_llm_provider_registry(settings)
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


def test_generation_api_runs_ten_step_stub_workflow_without_fake_verification(
    client: TestClient, database_path: Path, monkeypatch: MonkeyPatch
) -> None:
    csrf = authenticate(client)
    # Real-shaped, test-local provider (source_kind='live'); never in production.
    # Registered under the real key so the schema stays honest.
    client.app.state.llm_providers.replace(StubLLMProvider(key="openai_compatible"))
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
        "provider": "openai_compatible",
        "model": "stub-sports-writer-v1",
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
    assert preview.json()["provider"]["key"] == "openai_compatible"

    created = client.post(
        "/api/v1/generations",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "generation-test-1"},
        json=payload,
    )
    assert created.status_code == 202, created.text
    run_id = UUID(created.json()["id"])
    assert created.json()["status"] == "queued"
    assert created.json()["metadata"]["source_kind"] == "live"

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
    assert result["final_output"]["source_kind"] == "live"
    assert result["final_output"]["tts_en"].startswith("STUB LLM OUTPUT")
    assert 200 <= len(result["final_output"]["tts_en"]) <= 220
    assert result["validation_result"]["valid"] is True
    assert result["validation_result"]["warnings"] == 1
    assert result["rewrite_count"] <= payload["model_config"]["max_rewrites"]
    assert result["token_usage"]["total_tokens"] > 0
    assert Decimal(str(result["estimated_cost"])) == 0

    evidence = client.get(f"/api/v1/generations/{run_id}/evidence")
    assert evidence.status_code == 200, evidence.text
    evidence_payload = evidence.json()
    assert evidence_payload["contract_version"] == "generation-evidence-v1"
    assert evidence_payload["run_id"] == str(run_id)
    assert len(evidence_payload["input_hash"]) == 64
    assert evidence_payload["evidence_status"] == "unavailable"
    assert evidence_payload["source_count"] == 0
    assert evidence_payload["verification_status"] == "verification_incomplete"
    assert evidence_payload["step_statuses"]

    # ── B 组字段完整性验证 ────────────────────────────────────────────────────
    final = result["final_output"]
    tts_len = len(final["tts_en"])
    # spoken_char_count 必须由后端计算且与 tts_en 长度一致
    assert final["spoken_char_count"] == tts_len, (
        f"spoken_char_count ({final['spoken_char_count']}) != len(tts_en) ({tts_len})"
    )
    # verification_status 必须从 run 对象复制，不允许 LLM 覆盖
    assert final["verification_status"] == result["verification_status"]
    # B 组核心字段必须全部存在
    for b_field in (
        "event_identity",
        "story_format",
        "central_question",
        "selected_hook",
        "cmssml",
        "ev3",
        "story_architecture",
    ):
        assert b_field in final, f"B 组字段缺失：{b_field}"
    # lcr_enabled 必须是布尔值
    assert isinstance(final["lcr_enabled"], bool), (
        f"lcr_enabled 应为布尔值，实际：{type(final['lcr_enabled'])}"
    )
    # tts_en 必须是单行（后端 final_formatting 后处理确保）
    assert "\n" not in final["tts_en"]
    assert "\r" not in final["tts_en"]

    text_export = client.get(f"/api/v1/generations/{run_id}/export", params={"format": "txt"})
    assert text_export.status_code == 200
    assert "英文 TTS" in text_export.text
    json_export = client.get(f"/api/v1/generations/{run_id}/export", params={"format": "json"})
    assert json_export.status_code == 200
    assert json_export.json()["id"] == str(run_id)


def test_default_char_range_follows_v7_9_original() -> None:
    """7.9 原始默认值为 1180–1220，不是历史偏移值 1200–1250。"""
    assert DEFAULT_MIN_CHARS == 1180
    assert DEFAULT_MAX_CHARS == 1220


def test_validate_final_bundle_requires_all_b_group_fields() -> None:
    """B 组 8 个核心字段必须全部存在才能通过校验。"""
    # 最小合法包（含所有 A 组 + B 组必需字段）
    tts = "A" * 200
    valid_bundle: dict = {
        # A 组
        "event_fact_summary": "Test summary",
        "fact_sources": [],
        "story_value": {"qualified": True},
        "tts_en": tts,
        "translation_zh": "测试翻译",
        "video_title_en": "Test Title",
        "video_title_zh": "测试标题",
        "search_keywords": ["test"],
        "material_keywords": ["footage"],
        "tags": ["#test"],
        "project_filename": "测试文件",
        "qa_report": {},
        "used_rules": [],
        "rewrite_reasons": [],
        # B 组
        "spoken_char_count": len(tts),
        "event_identity": {"sport": "basketball"},
        "story_format": "consequence-first-decision",
        "central_question": "What caused the outcome?",
        "selected_hook": {"type": "scene-first-anomaly", "score": 80, "text": "Hook text"},
        "cmssml": tts,
        "ev3": tts,
        "story_architecture": {"primary_format": "consequence-first-decision"},
    }
    assert validate_final_bundle(valid_bundle) == []

    # 缺少单个 B 组字段时应报错
    for b_field in (
        "spoken_char_count",
        "event_identity",
        "story_format",
        "central_question",
        "selected_hook",
        "cmssml",
        "ev3",
        "story_architecture",
    ):
        incomplete = {k: v for k, v in valid_bundle.items() if k != b_field}
        errors = validate_final_bundle(incomplete)
        assert any(b_field in e for e in errors), f"缺少 {b_field} 时应报错，实际返回：{errors}"


def test_validate_final_bundle_spoken_char_count_must_match_tts() -> None:
    """spoken_char_count 必须等于 tts_en 的实际字符长度。"""
    tts = "B" * 150
    bundle: dict = {
        "event_fact_summary": "s",
        "fact_sources": [],
        "story_value": {},
        "tts_en": tts,
        "translation_zh": "t",
        "video_title_en": "e",
        "video_title_zh": "c",
        "search_keywords": [],
        "material_keywords": [],
        "tags": [],
        "project_filename": "文件名",
        "qa_report": {},
        "used_rules": [],
        "rewrite_reasons": [],
        "spoken_char_count": 999,  # 故意错误
        "event_identity": {},
        "story_format": "chain-reaction",
        "central_question": "?",
        "selected_hook": {},
        "cmssml": tts,
        "ev3": tts,
        "story_architecture": {},
    }
    errors = validate_final_bundle(bundle)
    assert any("spoken_char_count" in e for e in errors)

    # 修正后应通过
    bundle["spoken_char_count"] = len(tts)
    assert validate_final_bundle(bundle) == []


def test_validate_final_bundle_rejects_multiline_tts() -> None:
    """tts_en 含换行符时应报错。"""
    tts = "Line one.\nLine two."
    bundle: dict = {
        "event_fact_summary": "s",
        "fact_sources": [],
        "story_value": {},
        "tts_en": tts,
        "translation_zh": "t",
        "video_title_en": "e",
        "video_title_zh": "c",
        "search_keywords": [],
        "material_keywords": [],
        "tags": [],
        "project_filename": "文件名",
        "qa_report": {},
        "used_rules": [],
        "rewrite_reasons": [],
        "spoken_char_count": len(tts),
        "event_identity": {},
        "story_format": "chain-reaction",
        "central_question": "?",
        "selected_hook": {},
        "cmssml": "single line",
        "ev3": "single line",
        "story_architecture": {},
    }
    errors = validate_final_bundle(bundle)
    assert any("单行" in e or "换行" in e for e in errors)


def test_validate_final_bundle_lcr_enabled_must_be_bool() -> None:
    """lcr_enabled 如存在必须是布尔值，字符串 'true' 不可接受。"""
    tts = "C" * 100
    bundle: dict = {
        "event_fact_summary": "s",
        "fact_sources": [],
        "story_value": {},
        "tts_en": tts,
        "translation_zh": "t",
        "video_title_en": "e",
        "video_title_zh": "c",
        "search_keywords": [],
        "material_keywords": [],
        "tags": [],
        "project_filename": "文件名",
        "qa_report": {},
        "used_rules": [],
        "rewrite_reasons": [],
        "spoken_char_count": len(tts),
        "event_identity": {},
        "story_format": "chain-reaction",
        "central_question": "?",
        "selected_hook": {},
        "cmssml": tts,
        "ev3": tts,
        "story_architecture": {},
        "lcr_enabled": "true",  # 应该是布尔值
    }
    errors = validate_final_bundle(bundle)
    assert any("lcr_enabled" in e for e in errors)

    bundle["lcr_enabled"] = False
    # B 组字段合法，其余字段满足时应通过
    assert validate_final_bundle(bundle) == []


def test_generation_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/prompts").status_code == 401
    assert client.get("/api/v1/workflows").status_code == 401
    assert client.get("/api/v1/generations").status_code == 401
