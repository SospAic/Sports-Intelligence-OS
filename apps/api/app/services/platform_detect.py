"""Heuristics that infer a platform from a profile / channel URL.

Adding an account should be frictionless: the operator pastes a profile URL
and the system decides which platform it belongs to instead of forcing a
manual platform pick. The mapping below is intentionally conservative — it
only matches hostnames we actually support, so an unrecognised URL fails with
a clear validation error rather than silently picking the wrong adapter.
"""

from urllib.parse import urlparse

# Ordered so that the most specific hostnames win (e.g. ``youtu.be`` before a
# generic fallback). Each entry maps a hostname suffix to a platform key.
_HOST_TO_PLATFORM: tuple[tuple[str, str], ...] = (
    ("youtube.com", "youtube"),
    ("youtu.be", "youtube"),
    ("youtube", "youtube"),
    ("tiktok.com", "tiktok"),
    ("tiktok", "tiktok"),
    ("douyin.com", "douyin"),
    ("v.douyin.com", "douyin"),
    ("iesdouyin.com", "douyin"),
    ("douyin", "douyin"),
    ("bilibili.com", "bilibili"),
    ("b23.tv", "bilibili"),
    ("bilibili", "bilibili"),
)


def detect_platform_key_from_url(raw_url: str) -> str | None:
    """Return the platform key implied by ``raw_url``, or ``None`` if unknown.

    Accepts full URLs (``https://www.youtube.com/@foo``), bare handles that
    already carry a platform hint (``@youtube/foo``), and short links. Returns
    ``None`` for anything that does not clearly map to a supported platform so
    the caller can surface a precise "无法识别平台" message.
    """

    if not raw_url:
        return None
    candidate = raw_url.strip()
    if not candidate:
        return None

    lowered = candidate.casefold()
    # Bare handle syntax: "@platform/..." or "@platform_name/..." (e.g. a
    # TikTok share string). Treat the token after '@' as a platform hint.
    if lowered.startswith("@"):
        handle = lowered[1:].split("/", 1)[0].split("?", 1)[0]
        for host, key in _HOST_TO_PLATFORM:
            if handle == host or handle == key:
                return key

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    if not host and parsed.path:
        # No scheme provided; the path may itself be a hostname-like string.
        host = parsed.path.split("/", 1)[0].casefold()

    if not host:
        return None

    for suffix, key in _HOST_TO_PLATFORM:
        if host == suffix or host.endswith("." + suffix):
            return key
    return None
