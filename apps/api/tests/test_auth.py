from fastapi.testclient import TestClient

from .conftest import TEST_PASSWORD


def login(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()


def test_live_health_check_does_not_require_authentication(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api", "version": "0.1.0", "checks": None}


def test_current_user_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "authentication_required"


def test_login_rejects_invalid_credentials_without_leaking_account_state(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert "missing@example.com" not in response.text


def test_login_rate_limit_uses_hashed_identity_and_returns_retry_after(
    client: TestClient,
) -> None:
    for _ in range(3):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "login_rate_limited"
    assert blocked.headers["retry-after"] == "900"
    assert "admin@example.com" not in blocked.text


def test_login_current_user_csrf_and_logout_flow(client: TestClient) -> None:
    auth = login(client)
    assert auth["user"]["email"] == "admin@example.com"
    assert "password" not in str(auth).casefold()
    assert "sio_session" in client.cookies

    me_response = client.get("/api/v1/me")
    assert me_response.status_code == 200
    assert me_response.json()["memberships"] == [
        {
            "workspace_id": me_response.json()["memberships"][0]["workspace_id"],
            "workspace_name": "测试工作区",
            "role": "owner",
        }
    ]

    missing_csrf = client.post("/api/v1/auth/logout")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_validation_failed"

    csrf_response = client.get("/api/v1/auth/csrf")
    assert csrf_response.status_code == 200
    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf_response.json()["csrf_token"]},
    )
    assert logout_response.status_code == 204
    assert client.get("/api/v1/me").status_code == 401
