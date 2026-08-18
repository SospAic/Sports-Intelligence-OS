from app.services.sports_catalog import (
    GENERAL_SPORTS,
    MAINSTREAM_SPORTS,
    SPORTS_CATALOG,
    sport_profile_keywords,
)

from .conftest import TEST_PASSWORD


def test_hotspot_sports_catalog_has_the_required_two_tiers() -> None:
    assert len(MAINSTREAM_SPORTS) == 50
    assert len(GENERAL_SPORTS) == 30
    assert len({item.key for item in SPORTS_CATALOG}) == 80
    assert all(item.default_target == 50 for item in MAINSTREAM_SPORTS)
    assert all(item.default_target == 10 for item in GENERAL_SPORTS)


def test_hotspot_sports_catalog_exposes_real_query_aliases() -> None:
    aliases = dict(sport_profile_keywords())
    assert "basketball" in aliases
    assert "Basketball" in aliases["basketball"]
    assert "Formula 1" in aliases["formula1"]
    assert "匹克球" in aliases["pickleball"]


def test_hotspot_sports_catalog_endpoint_exposes_plan(client) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert login.status_code == 200, login.text
    response = client.get("/api/v1/trends/sports-catalog?window_hours=24")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mainstream_count"] == 50
    assert body["general_count"] == 30
    assert len(body["items"]) == 80
    assert {item["coverage_status"] for item in body["items"]} <= {
        "met",
        "limited_by_source",
        "not_collected",
    }
