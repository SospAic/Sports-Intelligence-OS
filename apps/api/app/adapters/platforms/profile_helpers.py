"""Cross-platform account *profile text* normalization & guard logic.

Sibling of :mod:`avatar_helpers`. Where that module protects the account
``avatar_url`` field, this one protects the textual identity fields — today
``display_name`` — and it must behave **identically for all four platforms**
(YouTube, TikTok, Douyin, Bilibili). Account-layer rules are written once here
so they cannot drift per-adapter.

Why this exists
---------------
``services/sync.py`` used to guard ``display_name`` with a small exact-match
error-page set (``404 Not Found``, ``页面不存在``, ...). That caught deleted
YouTube channels but let two other real corruption shapes through, both of
which are present in the live database as historical rows:

* ``@https://www.tiktok.com/@olympicsbringsustogether`` — the locator (a full
  URL) leaked into the display name instead of the handle. Any name that is
  really a URL is never a human-authored channel name.
* ``的抖音`` — the Douyin page title is ``<nickname>的抖音``; when the nickname
  fails to render (bot wall / slow hydration) the scrape keeps only the bare
  suffix. The remaining string is grammatically headless and identifies no
  account.

Both are *scrape failures wearing a valid-looking string*, so they pass a
simple "is it non-empty" check and get persisted, permanently mislabelling the
account. The guard below rejects them before they are written.
"""
from __future__ import annotations

# Exact (case/whitespace-normalized) strings that mean "the page we scraped was
# an error page", not an account name.
_ERROR_PAGE_TITLES: frozenset[str] = frozenset(
    {
        "404",
        "404 not found",
        "not found",
        "page not found",
        "页面不存在",
        "内容不存在",
        "视频不存在",
        "作品不存在",
        "该账号不存在",
        "用户不存在",
        "账号已注销",
        "error",
        "服务器错误",
    }
)

# Bare platform suffixes. A Douyin/Bilibili/Kuaishou page title is
# ``<nickname><suffix>``; if the string consists of *only* the suffix, the
# nickname failed to render and the name is meaningless. These are matched as
# the WHOLE normalized string — a real account called e.g. "老王的抖音" keeps
# its nickname and is therefore never rejected.
_BARE_PLATFORM_SUFFIXES: frozenset[str] = frozenset(
    {
        "的抖音",
        "的抖音号",
        "抖音",
        "的哔哩哔哩",
        "的bilibili",
        "哔哩哔哩",
        "bilibili",
        "的快手",
        "快手",
        "的微博",
        "微博",
        "的主页",
        "的个人主页",
        "个人主页",
        "主页",
        "untitled",
        "unnamed",
    }
)


def _normalize_text(value: str | None) -> str:
    """Casefold and collapse all whitespace runs to single spaces."""
    if not value:
        return ""
    return " ".join(value.casefold().split())


def is_error_page_title(value: str | None) -> bool:
    """Return ``True`` if *value* is an error-page title rather than a name."""
    return _normalize_text(value) in _ERROR_PAGE_TITLES


def is_invalid_display_name(value: str | None) -> bool:
    """Return ``True`` if *value* must not be persisted as an account name.

    Rejects, uniformly across the four platforms:

    * empty / whitespace-only values;
    * error-page titles (deleted or unavailable account pages);
    * values that are really URLs — including the ``@``-prefixed form produced
      by handle-style adapters when the locator was pasted as a full link;
    * bare platform suffixes left over when the nickname failed to render.

    A value that is merely *unusual* (emoji, punctuation, non-Latin script,
    a nickname that happens to contain a platform word) is accepted: this
    guard only rejects shapes that cannot be a real name.
    """
    normalized = _normalize_text(value)
    if not normalized:
        return True
    if normalized in _ERROR_PAGE_TITLES:
        return True
    if normalized in _BARE_PLATFORM_SUFFIXES:
        return True
    # A display name is never a URL. Strip a leading handle marker first so the
    # TikTok "@<pasted url>" corruption is caught too.
    unprefixed = normalized.lstrip("@").strip()
    if unprefixed.startswith(("http://", "https://")) or "://" in unprefixed:
        return True
    if unprefixed.startswith("www.") and " " not in unprefixed:
        return True
    return False


def should_update_display_name(old_name: str | None, new_name: str | None) -> bool:
    """Decide whether the sync layer should overwrite ``old_name``.

    Mirrors :func:`avatar_helpers.should_update_avatar`: an invalid freshly
    scraped value never overwrites a stored one, and an identical value is
    skipped. Callers must still honour a manual override flag
    (``display_name_source == "manual"``) before consulting this helper.
    """
    if is_invalid_display_name(new_name):
        return False
    fresh = (new_name or "").strip()
    stored = (old_name or "").strip()
    if not stored:
        return True
    return fresh != stored
