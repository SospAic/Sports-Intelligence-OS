"""Tests for the account-avatar local-archive route (``GET /accounts/{id}/avatar``).

The route lazily caches a platform avatar under ``MEDIA_ROOT/avatars`` on first
request and serves the permanent local copy afterwards; a miss returns 404 so
the frontend can fall back to the remote URL and then initials.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from .conftest import TEST_PLATFORM_ID
from .test_monitoring_api import authenticate

# Minimal 1x1 PNG — enough to assert the bytes round-trip through the route.
FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00"
    b"\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_with_avatar(client: TestClient, csrf_token: str, avatar_url: str) -> dict:
    response = client.post(
        "/api/v1/accounts",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "platform_id": str(TEST_PLATFORM_ID),
            "external_id": f"avatar-acct-{uuid4().hex[:8]}",
            "username": "avatar_creator",
            "display_name": "头像账号",
            "avatar_url": avatar_url,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_account_avatar_is_fetched_cached_and_served(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    fetch_calls: list[str] = []

    def fake_fetch(url: str, timeout: int = 10) -> bytes:
        fetch_calls.append(url)
        return FAKE_PNG

    monkeypatch.setattr("app.api.routes.media._fetch_remote_bytes", fake_fetch)

    csrf_token = authenticate(client)
    account = _create_with_avatar(client, csrf_token, "https://example.com/avatar.png")

    # First request fetches the remote avatar and caches it locally.
    first = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert first.status_code == 200, first.text
    assert first.content == FAKE_PNG
    assert len(fetch_calls) == 1

    # Second request is served from the local cache (no new remote fetch).
    second = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert second.status_code == 200
    assert second.content == FAKE_PNG
    assert len(fetch_calls) == 1

    # The cached file exists under MEDIA_ROOT/avatars.
    assert list(tmp_path.glob("avatars/*"))


def test_account_avatar_cache_invalidated_on_url_change(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Changing an account's avatar_url must invalidate the local cache even
    when the new URL keeps the same file extension — otherwise the route keeps
    serving the previously cached, now-wrong image."""
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    fetch_calls: list[str] = []

    def fake_fetch(url: str, timeout: int = 10) -> bytes:
        fetch_calls.append(url)
        return FAKE_PNG

    monkeypatch.setattr("app.api.routes.media._fetch_remote_bytes", fake_fetch)

    csrf_token = authenticate(client)
    account = _create_with_avatar(client, csrf_token, "https://example.com/avatar.png")

    first = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert first.status_code == 200
    assert len(fetch_calls) == 1

    # Re-request: served from cache, no new fetch.
    second = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert second.status_code == 200
    assert len(fetch_calls) == 1

    # Update the avatar URL (same extension) and request again.
    patch = client.patch(
        f"/api/v1/accounts/{account['id']}",
        headers={"X-CSRF-Token": csrf_token},
        json={"avatar_url": "https://example.com/new-avatar.png"},
    )
    assert patch.status_code == 200, patch.text

    third = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert third.status_code == 200
    assert third.content == FAKE_PNG
    # The new URL had to be fetched — the stale cached copy was not served.
    assert len(fetch_calls) == 2
    assert fetch_calls[-1] == "https://example.com/new-avatar.png"


def test_avatar_cache_path_depends_on_url() -> None:
    """Two different URLs (same extension) must map to different cache files,
    and the same URL must be deterministic — this is what stops a changed
    remote avatar from silently serving the old local copy."""
    from app.api.routes.media import _avatar_cache_path

    aid = uuid4()
    a = _avatar_cache_path(aid, "https://example.com/a.png")
    b = _avatar_cache_path(aid, "https://example.com/b.png")
    assert a != b
    assert _avatar_cache_path(aid, "https://example.com/a.png") == a
    assert str(aid) in a


def test_account_avatar_404_without_url(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "app.api.routes.media._fetch_remote_bytes",
        lambda url, timeout=10: FAKE_PNG,
    )
    csrf_token = authenticate(client)
    # Account created without an avatar_url (None) -> route must 404 so the
    # frontend falls back to the remote URL and then initials.
    account = _create_with_avatar(client, csrf_token, None)
    response = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert response.status_code == 404


def test_account_avatar_404_when_fetch_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("app.api.routes.media.MEDIA_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "app.api.routes.media._fetch_remote_bytes",
        lambda url, timeout=10: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    csrf_token = authenticate(client)
    account = _create_with_avatar(client, csrf_token, "https://example.com/avatar.png")
    response = client.get(f"/api/v1/accounts/{account['id']}/avatar")
    assert response.status_code == 404


def test_account_avatar_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/accounts/00000000-0000-0000-0000-000000000000/avatar")
    assert response.status_code == 401
