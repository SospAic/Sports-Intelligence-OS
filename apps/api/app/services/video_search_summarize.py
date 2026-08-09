"""Statistical summary + heuristic sentiment/heat for merged video-search results.

This is the v1 of the "auto-summary" capability. It ALWAYS returns a
statistical digest (totals, platform/engine distribution, top items) plus a
per-item heuristic sentiment and a heat score derived from the match score, so
the merged-results view is useful even with no LLM gateway configured.

An LLM-generated narrative (``llm_summary``) is left as a reserved field for
when the LLM gateway is wired up; the endpoint degrades gracefully without it.
"""

from __future__ import annotations

from collections import Counter

_POSITIVE = {
    "好",
    "赞",
    "精彩",
    "强",
    "赢",
    "冠军",
    "夺冠",
    "突破",
    "燃",
    "惊喜",
    "完美",
    "成功",
    "领先",
    "优势",
    "棒",
    "喜",
    "热爱",
    "高光",
    "nice",
    "good",
    "win",
    "champion",
    "great",
    "amazing",
    "best",
    "perfect",
    "breakthrough",
    "love",
    "highlight",
}
_NEGATIVE = {
    "差",
    "败",
    "输",
    "争议",
    "问题",
    "崩",
    "丑闻",
    "质疑",
    "失败",
    "弱",
    "落后",
    "劣势",
    "痛",
    "惨",
    "失误",
    "崩盘",
    "抗议",
    "bad",
    "loss",
    "lose",
    "fail",
    "failed",
    "controversy",
    "problem",
    "crash",
    "weak",
    "error",
    "protest",
}


def _sentiment(text: str) -> str:
    if not text:
        return "neutral"
    low = text.lower()
    pos = sum(1 for w in _POSITIVE if w in low)
    neg = sum(1 for w in _NEGATIVE if w in low)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _heat(item: dict) -> float:
    score = float(item.get("score") or 0.0)
    return max(0.0, min(1.0, score))


def summarize_results(payload: dict) -> dict:
    items = list(payload.get("items") or [])
    total = len(items)
    platform_distribution = dict(Counter(i.get("platform") or "unknown" for i in items))
    engine_distribution = dict(Counter(i.get("engine") or "unknown" for i in items))
    scored = sorted(items, key=lambda x: float(x.get("score") or 0.0), reverse=True)
    top_items = [
        {
            "id": i.get("id"),
            "title": i.get("title") or "",
            "platform": i.get("platform") or "",
            "engine": i.get("engine") or "",
            "score": float(i.get("score") or 0.0),
        }
        for i in scored[:5]
    ]
    out_items = [
        {
            "id": i.get("id"),
            "sentiment": _sentiment(f"{i.get('title') or ''} {i.get('snippet') or ''}"),
            "heat": _heat(i),
        }
        for i in items
    ]
    return {
        "total": total,
        "platform_distribution": platform_distribution,
        "engine_distribution": engine_distribution,
        "top_items": top_items,
        "items": out_items,
        "llm_summary": None,
        "llm_available": False,
    }
