from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

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
    required = {
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
    }
    missing = sorted(required - set(bundle))
    errors = [f"最终输出缺少字段：{item}" for item in missing]
    filename = bundle.get("project_filename")
    if isinstance(filename, str) and len(filename) > 10:
        errors.append("工程文件名超过十个字符")
    if not isinstance(bundle.get("tts_en"), str):
        errors.append("tts_en 必须是字符串")
    return errors


def aggregate_usage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "input_tokens": sum(int(item.get("input_tokens", 0)) for item in records),
        "output_tokens": sum(int(item.get("output_tokens", 0)) for item in records),
        "total_tokens": sum(int(item.get("total_tokens", 0)) for item in records),
        "sources": sorted({str(item.get("source", "unavailable")) for item in records}),
    }
