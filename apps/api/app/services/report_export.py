"""Server-side rendering of intelligence reports (Markdown + printable HTML).

No third-party renderer is involved: the Markdown is assembled with plain
string formatting and the printable HTML is a small standalone document that
the browser turns into a PDF via print-to-PDF. Both artefacts are built from
the same payload so the two downloads can never drift apart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any

#: Snippets are evidence excerpts, not full transcripts - keep the report short.
MAX_SNIPPET_CHARS = 600

ENGINE_LABELS = {"llm": "LLM 分析", "local": "本地检索"}

DEFAULT_TITLE = "体育情报简报"

_HTML_STYLE = """
@page { margin: 18mm 16mm; }
body { font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
       color: #111827; line-height: 1.6; font-size: 12px; margin: 0; }
h1 { font-size: 22px; margin: 0 0 12px; }
h2 { font-size: 14px; margin: 20px 0 6px; page-break-after: avoid; }
.meta { list-style: none; padding: 0; margin: 0 0 16px;
        border-left: 3px solid #0891b2; padding-left: 10px; color: #374151; }
.meta li { margin: 2px 0; }
.summary { background: #f1f5f9; padding: 10px 12px; border-radius: 6px;
           margin: 0 0 16px; }
article { page-break-inside: avoid; border-top: 1px solid #e5e7eb;
          padding-top: 10px; margin-top: 12px; }
article dl { display: grid; grid-template-columns: 84px 1fr; gap: 2px 8px;
             margin: 0 0 6px; }
article dt { color: #6b7280; }
article dd { margin: 0; word-break: break-all; }
.snippet { margin: 0; padding: 8px 10px; background: #f8fafc;
           border-left: 3px solid #cbd5e1; color: #374151; }
.empty { color: #6b7280; }
a { color: #0e7490; text-decoration: none; }
"""


def _clean(value: object) -> str:
    """Collapse whitespace so a value always stays on a single line."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _score_text(value: object) -> str:
    """Render a 0-1 relevance score as a percentage, tolerating bad input."""
    if value is None:
        return "—"
    try:
        return f"{round(float(str(value)) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _snippet(value: object) -> str:
    text = _clean(value)
    if len(text) > MAX_SNIPPET_CHARS:
        return f"{text[:MAX_SNIPPET_CHARS]}…"
    return text


def _engine_label(value: object) -> str:
    key = _clean(value)
    return ENGINE_LABELS.get(key, key or "未知引擎")


def _source_line(item: dict[str, Any]) -> str:
    platform = _clean(item.get("platform")) or "未知平台"
    account = _clean(item.get("account"))
    return f"{platform} · {account}" if account else platform


def _timestamp(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC)


def build_filename(generated_at: datetime) -> str:
    return f"intelligence-report-{generated_at.strftime('%Y%m%d-%H%M%S')}.md"


def render_markdown(payload: dict[str, Any], *, now: datetime | None = None) -> str:
    """Render the report payload as a Markdown document."""
    generated_at = _timestamp(now)
    items = list(payload.get("items") or [])
    title = _clean(payload.get("title")) or DEFAULT_TITLE
    query = _clean(payload.get("query")) or "（未提供检索词）"

    lines = [f"# {title}", ""]
    lines.append(f"- **检索词**：{query}")
    lines.append(f"- **生成时间**：{generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append(f"- **结果总数**：{len(items)}")
    mode = _clean(payload.get("mode"))
    if mode:
        lines.append(f"- **检索模式**：{mode}")
    lines.append("")

    summary = _snippet(payload.get("summary"))
    if summary:
        lines.extend(["## 摘要", "", f"> {summary}", ""])

    lines.extend(["## 检索结果", ""])
    if not items:
        lines.extend(["本次导出没有命中结果。", ""])

    for index, item in enumerate(items, start=1):
        heading = _clean(item.get("title")) or "无标题"
        lines.append(f"### {index}. {heading}")
        lines.append("")
        lines.append(
            f"- **相关度**：{_score_text(item.get('score'))}"
            f" ｜ **引擎**：{_engine_label(item.get('engine'))}"
        )
        lines.append(f"- **来源**：{_source_line(item)}")
        published_at = _clean(item.get("published_at"))
        if published_at:
            lines.append(f"- **发布时间**：{published_at}")
        url = _clean(item.get("url"))
        lines.append(f"- **链接**：{f'<{url}>' if url else '—'}")
        badges = [_clean(badge) for badge in (item.get("badges") or [])]
        badges = [badge for badge in badges if badge]
        if badges:
            lines.append(f"- **标签**：{' / '.join(badges)}")
        lines.append("")
        snippet = _snippet(item.get("snippet"))
        if snippet:
            lines.extend([f"> {snippet}", ""])

    return "\n".join(lines).rstrip() + "\n"


def render_html(payload: dict[str, Any], *, now: datetime | None = None) -> str:
    """Render a standalone printable HTML document (browser print-to-PDF)."""
    generated_at = _timestamp(now)
    items = list(payload.get("items") or [])
    title = _clean(payload.get("title")) or DEFAULT_TITLE
    query = _clean(payload.get("query")) or "（未提供检索词）"

    parts = [
        f"<h1>{escape(title)}</h1>",
        "<ul class='meta'>",
        f"<li>检索词：{escape(query)}</li>",
        f"<li>生成时间：{generated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC</li>",
        f"<li>结果总数：{len(items)}</li>",
    ]
    mode = _clean(payload.get("mode"))
    if mode:
        parts.append(f"<li>检索模式：{escape(mode)}</li>")
    parts.append("</ul>")

    summary = _snippet(payload.get("summary"))
    if summary:
        parts.append(f"<p class='summary'>{escape(summary)}</p>")

    if not items:
        parts.append("<p class='empty'>本次导出没有命中结果。</p>")

    for index, item in enumerate(items, start=1):
        heading = escape(_clean(item.get("title")) or "无标题")
        url = _clean(item.get("url"))
        link = f"<a href='{escape(url, quote=True)}'>{escape(url)}</a>" if url else "—"
        rows = [
            ("相关度", escape(_score_text(item.get("score")))),
            ("引擎", escape(_engine_label(item.get("engine")))),
            ("来源", escape(_source_line(item))),
        ]
        published_at = _clean(item.get("published_at"))
        if published_at:
            rows.append(("发布时间", escape(published_at)))
        rows.append(("链接", link))
        badges = [escape(_clean(b)) for b in (item.get("badges") or []) if _clean(b)]
        if badges:
            rows.append(("标签", " / ".join(badges)))

        definitions = "".join(f"<dt>{key}</dt><dd>{value}</dd>" for key, value in rows)
        parts.append(f"<article><h2>{index}. {heading}</h2><dl>{definitions}</dl>")
        snippet = _snippet(item.get("snippet"))
        if snippet:
            parts.append(f"<p class='snippet'>{escape(snippet)}</p>")
        parts.append("</article>")

    body = "".join(parts)
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title><style>{_HTML_STYLE}</style></head>"
        f"<body>{body}</body></html>"
    )


def build_report(payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Build every artefact the export endpoint returns."""
    generated_at = _timestamp(now)
    return {
        "filename": build_filename(generated_at),
        "markdown": render_markdown(payload, now=generated_at),
        "html_document": render_html(payload, now=generated_at),
        "generated_at": generated_at,
        "total": len(payload.get("items") or []),
    }
