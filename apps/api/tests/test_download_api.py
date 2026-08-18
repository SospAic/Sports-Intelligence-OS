from fastapi.testclient import TestClient

from .conftest import TEST_PASSWORD


def test_download_submission_requires_csrf(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200

    response = client.post(
        "/api/v1/downloads",
        json={"url": "https://example.com/video"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_validation_failed"
