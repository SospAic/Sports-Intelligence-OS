from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from typing import Any

from app.providers.llm.base import (
    LLMHealth,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)


class MockLLMProvider(LLMProvider):
    key = "mock_llm"
    name = "Mock LLM（仅测试）"
    is_mock = True
    supports_streaming = True

    @property
    def configured(self) -> bool:
        return True

    async def validate_config(self, config: Mapping[str, Any]) -> None:
        if config.get("simulate_error"):
            raise ValueError("Mock LLM configured to simulate an error")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        minimum = int(request.parameters.get("target_min_chars", 1180))
        maximum = int(request.parameters.get("target_max_chars", 1220))
        target = max(minimum, min(maximum, (minimum + maximum) // 2))
        title = str(request.metadata.get("title") or "the supplied sports event").strip()
        base = (
            "MOCK TEST OUTPUT — This deterministic narration validates the Sports Intelligence "
            f"OS workflow for {title}. It does not claim live research or independent fact "
            "verification. The sequence remains tied to the supplied input, keeps each sentence "
            "focused on one job, and records every step for review. "
        )
        filler = (
            "The test follows the event timeline, separates supplied claims from verified facts, "
            "and preserves a clear cause-and-result structure without inventing competition data. "
        )
        narration = base
        while len(narration) < target:
            narration += filler
        narration = narration[:target].rstrip()
        if len(narration) < minimum:
            narration += " " * (minimum - len(narration))
        final_bundle: dict[str, Any] = {
            "event_fact_summary": "MOCK TEST OUTPUT：仅复述已冻结输入，不代表联网核实。",
            "fact_sources": request.metadata.get("sources", []),
            "story_value": {
                "qualified": True,
                "reason": "Mock provider workflow contract test only",
            },
            "tts_en": narration.replace("\n", " "),
            "translation_zh": "模拟测试输出：该内容只用于验证工作流，不代表真实联网生成结果。",
            "video_title_en": "🏟️ MOCK TEST — Sports Workflow Verification",
            "video_title_zh": "🏟️ 模拟测试｜体育工作流验证",
            "search_keywords": ["MOCK SPORTS WORKFLOW", "TEST EVENT TIMELINE"],
            "material_keywords": ["mock sports footage", "workflow test timeline"],
            "tags": ["MOCK", "TEST_ONLY", "SPORTS_WORKFLOW"],
            "project_filename": "模拟流程验证",
            "qa_report": {"provider": self.key, "mock": True},
            "used_rules": request.metadata.get("used_rules", []),
            "rewrite_reasons": request.metadata.get("rewrite_reasons", []),
            # B 组字段（7.9 完整输出包）
            # spoken_char_count 由后端 final_formatting 后处理自动计算，
            # 此处提供占位值；服务层会以 len(tts_en) 覆盖。
            "spoken_char_count": len(narration.replace("\n", " ")),
            "event_identity": {
                "sport": "MOCK",
                "league": None,
                "athletes": ["MOCK_ATHLETE"],
                "teams": [],
                "date": None,
                "location": None,
                "note": "Mock provider — event identity not derived from real facts",
            },
            "story_format": "consequence-first-decision",
            "story_format_reason": "Mock provider: default format selected for contract test.",
            "central_question": "MOCK: What caused the outcome in the supplied event?",
            "selected_hook": {
                "type": "scene-first-anomaly",
                "score": 75,
                "text": "MOCK TEST HOOK — opens on the anomalous moment.",
                "reason": "Mock provider: default hook selected for contract test.",
            },
            "cmssml": narration.replace("\n", " "),
            "ev3": narration.replace("\n", " "),
            "story_architecture": {
                "primary_format": "consequence-first-decision",
                "depth_axis": "micro-action-and-body-mechanics",
                "narrative_trajectory": "participant-action-trajectory",
                "lcr_enabled": False,
                "lcr_reason": "Mock provider: LCR conditions not evaluated.",
                "functional_turns": [],
                "note": "Mock provider — architecture not derived from real facts",
            },
            # C 组可选字段（ambiguous / 原文不完整）
            "lcr_enabled": False,
            "lcr_reason": None,
            "hook_candidates": [],
            "answer_word_map": None,
            "reaction_relay": None,
            "evidence_rewards": None,
            "exclusion_ladder": None,
            "dialogue_notes": None,
            "audio_performance_map": None,
            "tts_settings": None,
            "video_material_plan": None,
            "edit_map": None,
            "caption_map": None,
            "original_audio_plan": None,
            "srt_output": None,
            "source_kind": "mock",
        }
        step_key = str(request.metadata.get("step_key", "generate_draft"))
        content: str | Mapping[str, Any] = (
            final_bundle if step_key == "final_formatting" else narration
        )
        input_tokens = max(1, sum(len(item.content) for item in request.messages) // 4)
        output_size = len(json.dumps(content, ensure_ascii=False))
        usage = LLMUsage(
            input_tokens=input_tokens,
            output_tokens=max(1, output_size // 4),
            total_tokens=input_tokens + max(1, output_size // 4),
            source="estimated",
        )
        return LLMResponse(
            content=content,
            provider_request_id=f"mock-{request.idempotency_key}",
            model=request.model,
            finish_reason="stop",
            usage=usage,
            provider_metadata={"source_kind": "mock", "test_output": True},
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.generate(request)
        content = response.content
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        for start in range(0, len(text), 80):
            yield text[start : start + 80]

    async def estimate_cost(self, usage: LLMUsage, config: Mapping[str, Any]) -> Decimal | None:
        return Decimal("0")

    async def health_check(self) -> LLMHealth:
        return LLMHealth(status="ok", detail="Mock provider is available for test output only")
