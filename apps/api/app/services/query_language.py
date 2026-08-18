"""Small, deterministic helpers for language-aware platform searches."""

from __future__ import annotations


def detect_language(text: str) -> str:
    """Return the supported primary script language used by ``text``.

    This is intentionally a conservative script check.  It is used to decide
    whether an English platform query must be prepared; it is not presented as
    a full language-identification service.
    """

    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "zh"
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "ja"
    if any("\uac00" <= char <= "\ud7af" for char in text):
        return "ko"
    return "en"


def contains_cjk(text: str) -> bool:
    """Return whether text contains CJK characters unsuitable for an English query."""

    return any(
        ("\u4e00" <= char <= "\u9fff")
        or ("\u3040" <= char <= "\u30ff")
        or ("\uac00" <= char <= "\ud7af")
        for char in text
    )


def filter_english_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep results whose returned title is compatible with an English search.

    Platform search APIs do not expose a reliable title-language field.  A
    CJK title is therefore excluded from an English-only result set rather
    than translated and shown as if it were an English source result.  Empty
    titles are retained because the platform may still provide a canonical URL
    and usable metrics.
    """

    filtered: list[dict[str, object]] = []
    for result in results:
        title = result.get("title")
        if not isinstance(title, str) or not title.strip() or not contains_cjk(title):
            filtered.append(result)
    return filtered
