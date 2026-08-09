"""Cross-platform avatar guard logic (A): default detection + update policy.

Pure-function checks (no DB / network) so they run in the default CI slice and
enforce the rule that avatar handling is identical across all four platforms.
"""

from app.adapters.platforms.avatar_helpers import (
    is_default_avatar_url,
    should_update_avatar,
)


# --- is_default_avatar_url -------------------------------------------------
def test_is_default_avatar_url_bilibili_noface():
    # Bilibili serves its no-custom-image placeholder as noface.gif/jpg.
    assert is_default_avatar_url("https://i0.hdslb.com/bfs/face/noface.gif") is True
    assert is_default_avatar_url("https://i0.hdslb.com/bfs/face/noface.jpg") is True


def test_is_default_avatar_url_generic_placeholders():
    assert is_default_avatar_url("https://cdn.example.com/default_avatar.png") is True
    assert is_default_avatar_url("https://cdn.example.com/avatar_default.webp") is True
    assert is_default_avatar_url("https://cdn.example.com/placeholder.gif") is True
    assert is_default_avatar_url("https://ui-avatars.com/api/?name=Jane") is True


def test_is_default_avatar_url_real_avatars_false():
    # Real, custom avatars must NOT be flagged as defaults.
    assert is_default_avatar_url("https://p16.tiktokcdn.com/real/avatar.jpg") is False
    assert is_default_avatar_url("https://yt3.ggpht.com/real/photo=xyz") is False
    assert is_default_avatar_url("https://i0.hdslb.com/bfs/face/abcdef123.jpg") is False
    assert is_default_avatar_url("https://p3-pc.douyinpic.com/aweme/real.webp") is False


def test_is_default_avatar_url_empty():
    assert is_default_avatar_url(None) is False
    assert is_default_avatar_url("") is False
    assert is_default_avatar_url("   ") is False


# --- should_update_avatar (the sync-layer guard) --------------------------
def test_should_update_first_capture():
    # Empty / missing stored value is always updated.
    assert should_update_avatar(None, "https://x/real.jpg") is True
    assert should_update_avatar("", "https://x/real.jpg") is True


def test_should_update_refuses_missing_new():
    # A missing new value never overwrites a stored one.
    assert should_update_avatar("https://x/old.jpg", None) is False
    assert should_update_avatar("https://x/old.jpg", "") is False


def test_should_update_refuses_default_new():
    # A platform default new value never overwrites a stored avatar.
    assert (
        should_update_avatar("https://x/old.jpg", "https://i0.hdslb.com/bfs/face/noface.gif")
        is False
    )


def test_should_update_same_value_skipped():
    # Identical value -> no needless re-fetch / re-cache.
    assert should_update_avatar("https://x/old.jpg", "https://x/old.jpg") is False


def test_should_update_replaces_default_with_real():
    # If a prior sync smeared a default, a fresh real avatar must win.
    assert (
        should_update_avatar("https://i0.hdslb.com/bfs/face/noface.gif", "https://x/new.jpg")
        is True
    )


def test_should_update_real_to_real_changed():
    assert should_update_avatar("https://x/old.jpg", "https://x/new.jpg") is True


def test_should_update_empty_to_default_refused():
    # Never seed a default placeholder into an empty account.
    assert should_update_avatar(None, "https://cdn.example.com/placeholder.png") is False
