"""Coverage for the server-side intelligence report renderer (no DB needed)."""

from datetime import UTC, datetime

from app.services.report_export import (
    MAX_SNIPPET_CHARS,
    build_filename,
    build_report,
    render_html,
    render_markdown,
)

_NOW = datetime(2026, 8, 9, 3, 14, 7, tzinfo=UTC)

_PAYLOAD = {
    "title": "世锦赛跳水简报",
    "query": "世锦赛 跳水",
    "mode": "hybrid",
    "summary": "共命中 2 条内容，均来自决赛集锦。",
    "items": [
        {
            "title": "女子十米台决赛集锦",
            "url": "https://example.com/watch?v=1",
            "engine": "local",
            "platform": "Bilibili",
            "account": "官方体育",
            "published_at": "2026-07-30",
            "score": 0.8642,
            "snippet": "全红婵第三跳\n获得满分。",
            "badges": ["向量", "字幕"],
        },
        {
            "title": "",
            "url": "",
            "engine": "llm",
            "platform": "",
            "score": None,
            "snippet": "",
        },
    ],
}


def test_markdown_header_carries_query_and_generated_time():
    md = render_markdown(_PAYLOAD, now=_NOW)
    assert md.startswith("# 世锦赛跳水简报\n")
    assert "- **检索词**：世锦赛 跳水" in md
    assert "- **生成时间**：2026-08-09 03:14:07 UTC" in md
    assert "- **结果总数**：2" in md
    assert "- **检索模式**：hybrid" in md
    assert "> 共命中 2 条内容，均来自决赛集锦。" in md
    assert md.endswith("\n")


def test_markdown_renders_score_link_and_snippet_per_item():
    md = render_markdown(_PAYLOAD, now=_NOW)
    assert "### 1. 女子十米台决赛集锦" in md
    assert "- **相关度**：86% ｜ **引擎**：本地检索" in md
    assert "- **来源**：Bilibili · 官方体育" in md
    assert "- **发布时间**：2026-07-30" in md
    assert "- **链接**：<https://example.com/watch?v=1>" in md
    assert "- **标签**：向量 / 字幕" in md
    # Newlines inside a snippet would break the blockquote - they are collapsed.
    assert "> 全红婵第三跳 获得满分。" in md


def test_markdown_falls_back_for_missing_fields():
    md = render_markdown(_PAYLOAD, now=_NOW)
    assert "### 2. 无标题" in md
    assert "- **相关度**：— ｜ **引擎**：LLM 分析" in md
    assert "- **来源**：未知平台" in md
    assert "- **链接**：—" in md


def test_markdown_without_items_states_no_hits():
    md = render_markdown({"query": "空查询"}, now=_NOW)
    assert "# 体育情报简报" in md
    assert "- **结果总数**：0" in md
    assert "本次导出没有命中结果。" in md
    assert "## 摘要" not in md


def test_markdown_truncates_long_snippets():
    payload = {"items": [{"title": "长文", "snippet": "字" * (MAX_SNIPPET_CHARS + 50)}]}
    md = render_markdown(payload, now=_NOW)
    assert f"> {'字' * MAX_SNIPPET_CHARS}…" in md


def test_html_document_escapes_untrusted_text():
    payload = {
        "title": "<script>alert(1)</script>",
        "items": [{"title": "a & b", "snippet": "<img src=x>"}],
    }
    html = render_html(payload, now=_NOW)
    assert html.startswith("<!DOCTYPE html>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "a &amp; b" in html
    assert "&lt;img src=x&gt;" in html


def test_build_report_bundles_both_artefacts():
    report = build_report(_PAYLOAD, now=_NOW)
    assert report["filename"] == "intelligence-report-20260809-031407.md"
    assert report["total"] == 2
    assert report["generated_at"] == _NOW
    assert report["markdown"] == render_markdown(_PAYLOAD, now=_NOW)
    assert report["html_document"] == render_html(_PAYLOAD, now=_NOW)


def test_build_filename_is_sortable():
    assert build_filename(_NOW).endswith(".md")
    assert build_filename(_NOW) < build_filename(_NOW.replace(year=2027))
