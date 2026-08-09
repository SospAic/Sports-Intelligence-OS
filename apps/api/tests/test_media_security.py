"""Security / traversal guards for media + download file serving.

These are pure-function checks (no DB, no network) so they run fast and are not
marked ``net`` — they belong in the default CI run.
"""

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.routes.media import (  # noqa: E402
    _allowed_files,
    _is_safe_avatar_url,
    _safe_media_path,
)


def test_safe_avatar_url_rejects_non_http():
    for url in ("file:///etc/passwd", "ftp://example.com/x", "data:text/plain,hi"):
        with pytest.raises(ValueError):
            _is_safe_avatar_url(url)


def test_safe_avatar_url_rejects_loopback_metadata_private():
    for url in (
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://0.0.0.0/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/x",
        "http://192.168.1.1/x",
        "http://172.16.0.1/x",
        "http://[::1]/x",
    ):
        with pytest.raises(ValueError):
            _is_safe_avatar_url(url)


def test_safe_avatar_url_allows_public(monkeypatch):
    def fake_getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET, 0, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    # Should not raise for a publicly-routable address.
    _is_safe_avatar_url("http://example.com/avatar.jpg")


def test_safe_media_path_blocks_traversal():
    assert _safe_media_path("../secret", "x.txt") is None
    assert _safe_media_path("abc/../../etc", "passwd") is None
    good = _safe_media_path("abc", "video.mp4")
    assert good is not None
    assert ".." not in good
    assert good.startswith(os.path.normpath(os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")))


def test_allowed_files_extracts_recorded_paths():
    media = {
        "base": "ws/1",
        "thumbnail": "thumb.jpg",
        "video": "video.mp4",
        "info_json": "info.json",
        "subtitles": [{"file": "a.vtt"}, {"file": "b.srt"}],
    }
    assert _allowed_files(media) == {
        "thumb.jpg",
        "video.mp4",
        "info.json",
        "a.vtt",
        "b.srt",
    }


def test_safe_avatar_url_allows_proxy_egress(monkeypatch):
    """The runtime rewrites public CDN hostnames to proxy egress ranges
    (198.18.0.0/15, fdfe:dcba:9876::/48); those must NOT be blocked, otherwise
    every legitimate avatar fails to cache (the original bug)."""

    def fake_getaddrinfo(host, port, *a, **k):
        return [
            (socket.AF_INET, 0, 0, "", ("198.18.0.232", 0)),
            (socket.AF_INET6, 0, 0, "", ("fdfe:dcba:9876::15", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    _is_safe_avatar_url("https://yt3.googleusercontent.com/avatar.jpg")
    _is_safe_avatar_url("https://p16-common-sign.tiktokcdn.com/avatar.jpg")


def test_cache_avatar_for_account_writes_file(tmp_path, monkeypatch):
    from app.api.routes.media import cache_avatar_for_account

    monkeypatch.setattr(
        "app.api.routes.media._fetch_remote_bytes", lambda url: b"FAKEIMAGE"
    )
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    import uuid

    aid = uuid.uuid4()
    assert cache_avatar_for_account(aid, "https://example.com/a.png") is True
    files = list(tmp_path.glob("avatars/*"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"FAKEIMAGE"


def test_cache_avatar_for_account_skips_when_cached(tmp_path, monkeypatch):
    from app.api.routes.media import cache_avatar_for_account

    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        return b"DATA"

    monkeypatch.setattr("app.api.routes.media._fetch_remote_bytes", fake_fetch)
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    import uuid

    aid = uuid.uuid4()
    assert cache_avatar_for_account(aid, "https://example.com/a.png") is True
    # Same URL -> second call must skip the re-download (different cache file
    # only when the URL changes, which it does not here).
    assert cache_avatar_for_account(aid, "https://example.com/a.png") is True
    assert calls["n"] == 1


def test_cache_avatar_for_account_returns_false_on_failure(tmp_path, monkeypatch):
    from app.api.routes.media import cache_avatar_for_account

    def fake_fetch(url):
        raise ValueError("blocked")

    monkeypatch.setattr("app.api.routes.media._fetch_remote_bytes", fake_fetch)
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    import uuid

    assert cache_avatar_for_account(uuid.uuid4(), "https://example.com/a.png") is False


# --- D: _fetch_remote_bytes content-type + size guards ---------------------
class _FakeAvatarResp:
    def __init__(self, content_type, content=b"x", content_length=None):
        self.headers = {}
        if content_type is not None:
            self.headers["content-type"] = content_type
        if content_length is not None:
            self.headers["content-length"] = str(content_length)
        self.content = content

    def raise_for_status(self):
        return None


class _FakeAvatarClient:
    def __init__(self, resp, *a, **k):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return self._resp


def test_fetch_remote_bytes_rejects_non_image(monkeypatch):
    from app.api.routes.media import _AVATAR_MAX_BYTES, _fetch_remote_bytes

    monkeypatch.setattr("app.api.routes.media._is_safe_avatar_url", lambda url: None)
    resp = _FakeAvatarResp("text/html; charset=utf-8", b"<html>")
    monkeypatch.setattr(
        "app.api.routes.media.httpx.Client", lambda *a, **k: _FakeAvatarClient(resp)
    )
    with pytest.raises(ValueError):
        _fetch_remote_bytes("https://example.com/login-wall")


def test_fetch_remote_bytes_rejects_oversize(monkeypatch):
    from app.api.routes.media import _AVATAR_MAX_BYTES, _fetch_remote_bytes

    monkeypatch.setattr("app.api.routes.media._is_safe_avatar_url", lambda url: None)
    resp = _FakeAvatarResp("image/png", b"x" * (_AVATAR_MAX_BYTES + 1))
    monkeypatch.setattr(
        "app.api.routes.media.httpx.Client", lambda *a, **k: _FakeAvatarClient(resp)
    )
    with pytest.raises(ValueError):
        _fetch_remote_bytes("https://example.com/huge.png")


def test_fetch_remote_bytes_accepts_image(monkeypatch):
    from app.api.routes.media import _fetch_remote_bytes

    monkeypatch.setattr("app.api.routes.media._is_safe_avatar_url", lambda url: None)
    resp = _FakeAvatarResp("image/png", b"\x89PNG")
    monkeypatch.setattr(
        "app.api.routes.media.httpx.Client", lambda *a, **k: _FakeAvatarClient(resp)
    )
    assert _fetch_remote_bytes("https://example.com/a.png") == b"\x89PNG"
