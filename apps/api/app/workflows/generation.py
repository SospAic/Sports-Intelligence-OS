from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

# 7.9 原始默认字符范围（约 1 分钟）
DEFAULT_MIN_CHARS: int = 1180
DEFAULT_MAX_CHARS: int = 1220

# 7.9 完整输出包：后端强制必需字段
# product_extension 字段（used_rules / rewrite_reasons / video_title_en / video_title_zh）
# 是产品层扩展，不在 Part 13 顶层定义，但本系统强制要求。
REQUIRED_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {
        # A 组：原有字段
        "event_fact_summary",
        "fact_sources",
        "story_value",
        "tts_en",
        "translation_zh",
        "video_title_en",
        "video_title_zh",
        "search_keywords",
        "material_keywords",
        "tags",
        "project_filename",
        "qa_report",
        "used_rules",
        "rewrite_reasons",
        # B 组：7.9 完整输出包新增核心字段（explicit / derived）
        "spoken_char_count",  # explicit: 精确字符数，后端计算，不依赖 LLM
        "event_identity",  # explicit: 事件精确识别（项目/赛事/人物/队伍/日期/地点）
        "story_format",  # explicit: 主故事格式（20 种之一）
        "central_question",  # explicit: 中心悬念/问题
        "selected_hook",  # explicit: 选定 Hook 及评分
        "cmssml",  # explicit: 单行 CMSSML 版本（去标签后与 tts_en 单词一致）
        "ev3",  # explicit: 单行 EV3 版本（去标签后与 tts_en 单词一致）
        "story_architecture",  # explicit: 故事架构（格式/深度轴/轨迹/LCR状态/AW映射）
    }
)

WORKFLOW_STEPS: tuple[tuple[str, str], ...] = (
    ("research_input", "Research Input"),
    ("normalize_facts", "Normalize Facts"),
    ("build_timeline", "Build Timeline"),
    ("story_qualification", "Story Qualification"),
    ("apply_rules", "Apply Rules"),
    ("generate_draft", "Generate Draft"),
    ("editorial_review", "Editorial Review"),
    ("qa_validation", "QA Validation"),
    ("automatic_rewrite", "Automatic Rewrite"),
    ("final_formatting", "Final Formatting"),
)


def workflow_definition() -> list[dict[str, Any]]:
    return [
        {"key": key, "name": name, "sort_order": index, "required": True}
        for index, (key, name) in enumerate(WORKFLOW_STEPS, start=1)
    ]


def extract_claims(payload: Mapping[str, Any]) -> list[str]:
    text_parts = [
        str(payload.get(key) or "").strip()
        for key in ("title", "summary", "content", "text", "description")
    ]
    text = " ".join(part for part in text_parts if part)
    sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", text) if item.strip()]
    if not sentences and text:
        sentences = [text]
    return sentences[:20]


def deterministic_qa(
    draft: str,
    *,
    target_min_chars: int,
    target_max_chars: int,
    verification_status: str,
    protected_answer_words: Sequence[str] = (),
    answer_reveal_min_ratio: float = 0.55,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    length = len(draft)
    if length < target_min_chars or length > target_max_chars:
        findings.append(
            {
                "code": "tts_length_out_of_range",
                "severity": "error",
                "message": f"英文 TTS 字符数 {length}，目标为 "
                + f"{target_min_chars}–{target_max_chars}",
                "rewrite_instruction": "调整英文 TTS 长度并保持事实与结构不变",
            }
        )
    if "\n" in draft or "\r" in draft:
        findings.append(
            {
                "code": "tts_must_be_single_line",
                "severity": "error",
                "message": "英文 TTS 必须保持一行",
                "rewrite_instruction": "移除换行并保留自然的句间连接",
            }
        )
    if verification_status != "corroborated":
        findings.append(
            {
                "code": "fact_verification_incomplete",
                "severity": "warning",
                "message": "当前证据不足以宣称已完成独立联网核实",
                "rewrite_instruction": None,
            }
        )
    reveal_ratio = max(0.0, min(1.0, answer_reveal_min_ratio))
    answer_checks: list[dict[str, Any]] = []
    for raw_word in protected_answer_words:
        word = raw_word.strip()
        if not word:
            continue
        match = re.search(rf"(?<!\w){re.escape(word)}(?!\w)", draft, flags=re.IGNORECASE)
        if match is None:
            answer_checks.append({"word": word, "first_ratio": None, "status": "missing"})
            findings.append(
                {
                    "code": "protected_answer_word_missing",
                    "severity": "error",
                    "message": f"受保护答案词未在文案中揭晓：{word}",
                    "rewrite_instruction": "在悬念成立后明确揭晓受保护答案词",
                }
            )
            continue
        first_ratio = match.start() / max(len(draft), 1)
        status = "passed" if first_ratio >= reveal_ratio else "revealed_too_early"
        answer_checks.append({"word": word, "first_ratio": round(first_ratio, 4), "status": status})
        if status != "passed":
            findings.append(
                {
                    "code": "protected_answer_word_revealed_too_early",
                    "severity": "error",
                    "message": f"受保护答案词在悬念建立前出现：{word}",
                    "rewrite_instruction": "将答案词首次出现移动到叙事后段的揭晓位置",
                }
            )
    errors = sum(item["severity"] == "error" for item in findings)
    return {
        "valid": errors == 0,
        "character_count": length,
        "target_min_chars": target_min_chars,
        "target_max_chars": target_max_chars,
        "errors": errors,
        "warnings": sum(item["severity"] == "warning" for item in findings),
        "findings": findings,
        "answer_protection": {
            "minimum_reveal_ratio": reveal_ratio,
            "checks": answer_checks,
        },
    }


def validate_final_bundle(bundle: Mapping[str, Any]) -> list[str]:
    """校验 7.9 完整输出包的必需字段和约束条件。

    字段分类：
    - A 组（原有 14 字段）：保持不变
    - B 组（新增 8 个核心字段）：7.9 Part 13 明确要求的结构化字段
    - C 组（可选字段）：ambiguous 原文不完整，允许 null 或缺失

    后端自动补入字段（不由本函数触发错误）：
    - spoken_char_count：由 final_formatting 步骤后处理从 tts_en 计算
    - verification_status：从 run.verification_status 复制，不允许 LLM 覆盖
    """
    missing = sorted(REQUIRED_OUTPUT_FIELDS - set(bundle))
    errors = [f"最终输出缺少字段：{item}" for item in missing]

    # tts_en 必须是非空字符串且单行
    tts = bundle.get("tts_en")
    if not isinstance(tts, str):
        errors.append("tts_en 必须是字符串")
    elif "\n" in tts or "\r" in tts:
        errors.append("tts_en 必须是单行（不含换行符）")

    # spoken_char_count 必须是整数且与 tts_en 长度一致
    char_count = bundle.get("spoken_char_count")
    if isinstance(tts, str) and char_count is not None:
        if not isinstance(char_count, int):
            errors.append("spoken_char_count 必须是整数")
        elif char_count != len(tts):
            errors.append(
                f"spoken_char_count ({char_count}) 与 tts_en 实际长度 ({len(tts)}) 不一致"
            )

    # project_filename 不超过 10 个字符
    filename = bundle.get("project_filename")
    if isinstance(filename, str) and len(filename) > 10:
        errors.append("工程文件名超过十个字符")

    # lcr_enabled 如果存在必须是布尔值（可选字段）
    lcr_enabled = bundle.get("lcr_enabled")
    if lcr_enabled is not None and not isinstance(lcr_enabled, bool):
        errors.append("lcr_enabled 必须是布尔值")

    # cmssml / ev3 必须是字符串（单行，不校验单词顺序——由 LLM Prompt 约束）
    for field in ("cmssml", "ev3"):
        value = bundle.get(field)
        if isinstance(value, str) and ("\n" in value or "\r" in value):
            errors.append(f"{field} 必须是单行字符串（不含换行符）")

    return errors


def aggregate_usage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in records),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in records),
        "total_tokens": sum(int(item.get("total_tokens", 0)) for item in records),
        "sources": sorted({str(item.get("source", "unavailable")) for item in records}),
    }
