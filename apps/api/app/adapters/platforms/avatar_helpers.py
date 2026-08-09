"""Cross-platform avatar normalization & guard logic.

This module is the single source of truth for avatar handling rules that must
be applied **identically for all four platforms** (YouTube, TikTok, Douyin,
Bilibili). It exists so a change to account-layer avatar behaviour is written
once and stays consistent across platforms, instead of drifting per-adapter.

Two public helpers:

* ``is_default_avatar_url`` — recognise a platform's placeholder / generated
  default avatar so it is never cached as if it were a real custom image.
* ``should_update_avatar`` — the guard used by the sync layer
  (``services/sync.py``) before overwriting an account's stored ``avatar_url``.
  It refuses to replace a real avatar with a missing or default value. This is
  exactly what previously let one shared default image overwrite good avatars
  for bot-walled accounts (e.g. three TikTok accounts all showing the same
  grey default).
"""

from __future__ import annotations

from urllib.parse import urlparse

# Substrings that identify a placeholder / default avatar. These are
# deliberately conservative: a real custom avatar URL must never match, or we
# would strip a good image. Entries are matched case-insensitively against the
# full URL.
#
# ``bilibili`` — Bilibili serves its no-custom-image placeholder as
# ``noface.gif`` / ``noface.jpg`` (host ``i0.hdslb.com/bfs/face/noface.gif``).
# ``generic`` — web placeholders shared across CDNs / frameworks.
_DEFAULT_AVATAR_MARKERS: dict[str, tuple[str, ...]] = {
    "bilibili": ("noface",),
    "generic": (
        "default_avatar",
        "default-avatar",
        "avatar_default",
        "placeholder",
        "blank-avatar",
        "blank_user",
        "no_avatar",
        "noavatar",
        "anon-avatar",
        "guest-avatar",
        "default-user",
        "default_profile",
        "profile_default",
    ),
}

# Known default-avatar hosts (matched as substrings of the hostname).
_DEFAULT_AVATAR_HOST_MARKERS: tuple[str, ...] = (
    "ui-avatars.com",  # generated initials image — treat as a placeholder
)


def _normalize(url: str | None) -> str | None:
    """Strip whitespace; return ``None`` for empty/whitespace-only input."""
    if not url:
        return None
    stripped = url.strip()
    return stripped or None


def is_default_avatar_url(url: str | None) -> bool:
    """Return ``True`` if *url* looks like a platform's placeholder/default avatar."""
    url = _normalize(url)
    if not url:
        return False
    low = url.lower()
    for markers in _DEFAULT_AVATAR_MARKERS.values():
        if any(marker in low for marker in markers):
            return True
    host = (urlparse(url).hostname or "").lower()
    if any(marker in host for marker in _DEFAULT_AVATAR_HOST_MARKERS):
        return True
    return False


def should_update_avatar(old_url: str | None, new_url: str | None) -> bool:
    """Decide whether the sync layer should overwrite ``old_url`` with ``new_url``.

    Rules (cross-platform, applied uniformly in ``services/sync.py``):

    * A missing / empty new value never overwrites anything.
    * A platform-default placeholder new value never overwrites a stored value
      (this is what previously smeared one shared default image across many
      bot-walled accounts).
    * An empty stored value is always updated (first capture).
    * Identical values are skipped (avoids a needless re-fetch / re-cache).
    """
    new_url = _normalize(new_url)
    if not new_url:
        return False
    if is_default_avatar_url(new_url):
        return False
    old_url = _normalize(old_url)
    if not old_url:
        return True
    if old_url == new_url:
        return False
    return True
