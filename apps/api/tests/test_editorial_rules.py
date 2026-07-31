import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.rules.parser import parse_v79_bytes
from app.rules.validation import validate_rules

from .conftest import TEST_PASSWORD

RULE_SOURCE = (
    Path(__file__).parents[3]
    / "data"
    / "rules"
    / (
        "ELITE_SPORTS_FACELESS_NARRATION_ENGINE_V7_9_LATE_CAUSE_REVEAL_"
        "REACTION_RELAY_ANSWER_WORD_PROTECTION_FULL.txt"
    )
)
EXPECTED_HASH = "9f69ee764fc9c33217699df584bba18ecd5d584af8ada3770e5c8779f9e824d6"


def authenticate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def test_complete_v79_source_parses_with_line_traceability() -> None:
    document = parse_v79_bytes(RULE_SOURCE.read_bytes())

    assert document.version == "7.9"
    assert document.source_hash == EXPECTED_HASH
    assert len(document.sections) == 816
    assert len(document.rules) == 1021
    assert any(rule.key == "kernel-29" for rule in document.rules)
    assert any(rule.key == "test-195" for rule in document.rules)
    assert all(rule.source_status == "full" for rule in document.rules)
    assert all(
        rule.source_reference and rule.source_reference.startswith("lines:")
        for rule in document.rules
    )


def test_rule_validation_detects_publish_blockers_and_warnings() -> None:
    rules = [
        SimpleNamespace(
            key="a",
            title="A",
            instruction="Do A",
            section_id=None,
            qa_check=None,
            is_mandatory=False,
            enabled=True,
            dependencies=["b"],
            conflicts=["b"],
            source_reference=None,
            source_status="unresolved",
        ),
        SimpleNamespace(
            key="b",
            title="B",
            instruction="Do B",
            section_id="section",
            qa_check="Check B",
            is_mandatory=False,
            enabled=True,
            dependencies=["a", "missing"],
            conflicts=[],
            source_reference="lines:2-3",
            source_status="full",
        ),
        SimpleNamespace(
            key="mandatory-disabled",
            title="Mandatory",
            instruction="Must remain enabled",
            section_id="section",
            qa_check="Check mandatory state",
            is_mandatory=True,
            enabled=False,
            dependencies=[],
            conflicts=[],
            source_reference="lines:4-5",
            source_status="full",
        ),
    ]

    issues = validate_rules(rules)
    codes = {issue.code for issue in issues}
    assert {
        "missing_section",
        "missing_qa",
        "mandatory_rule_disabled",
        "unresolved_source",
        "invalid_dependency",
        "dependency_conflict_overlap",
        "active_rule_conflict",
        "cyclic_dependency",
    } <= codes


def test_rule_import_version_edit_publish_compare_rollback_and_export(
    client: TestClient,
) -> None:
    csrf = authenticate(client)
    content = RULE_SOURCE.read_bytes().decode("utf-8")
    imported = client.post(
        "/api/v1/rules/import",
        headers={"X-CSRF-Token": csrf},
        json={
            "format": "txt",
            "filename": RULE_SOURCE.name,
            "content": content,
            "publish": True,
        },
    )
    assert imported.status_code == 201, imported.text
    result = imported.json()
    rule_set_id = result["rule_set"]["id"]
    published_id = result["version"]["id"]
    assert result["created"] is True
    assert result["version"]["source_hash"] == EXPECTED_HASH
    assert result["version"]["status"] == "published"
    assert result["version"]["section_count"] == 816
    assert result["version"]["rule_count"] == 1021
    assert result["validation"]["valid"] is True
    assert result["validation"]["warnings"] > 0

    duplicate = client.post(
        "/api/v1/rules/import",
        headers={"X-CSRF-Token": csrf},
        json={
            "format": "txt",
            "filename": RULE_SOURCE.name,
            "content": content,
            "publish": True,
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["created"] is False

    mandatory = client.get(
        f"/api/v1/rules/{rule_set_id}/versions/{published_id}/rules",
        params={"is_mandatory": True, "page_size": 1},
    )
    assert mandatory.status_code == 200
    mandatory_rule = mandatory.json()["items"][0]
    edited = client.patch(
        f"/api/v1/rules/{rule_set_id}/versions/{published_id}/rules/{mandatory_rule['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"enabled": False, "title": mandatory_rule["title"] + " — revised"},
    )
    assert edited.status_code == 200, edited.text
    edit_result = edited.json()
    assert edit_result["created_draft"] is True
    draft_id = edit_result["version_id"]
    draft_rule = edit_result["rule"]

    validation = client.post(
        f"/api/v1/rules/{rule_set_id}/versions/{draft_id}/validate",
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert any(item["code"] == "mandatory_rule_disabled" for item in validation.json()["issues"])
    blocked = client.post(
        f"/api/v1/rules/{rule_set_id}/versions/{draft_id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "must fail"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "rule_validation_failed"

    repaired = client.patch(
        f"/api/v1/rules/{rule_set_id}/versions/{draft_id}/rules/{draft_rule['id']}",
        headers={"X-CSRF-Token": csrf},
        json={"enabled": True},
    )
    assert repaired.status_code == 200
    published = client.post(
        f"/api/v1/rules/{rule_set_id}/versions/{draft_id}/publish",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "review complete"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    comparison = client.get(
        f"/api/v1/rules/{rule_set_id}/compare",
        params={"left": published_id, "right": draft_id},
    )
    assert comparison.status_code == 200
    assert comparison.json()["modified"] == 1
    assert comparison.json()["items"][0]["fields"] == ["title"]

    rollback = client.post(
        f"/api/v1/rules/{rule_set_id}/versions/{published_id}/rollback",
        headers={"X-CSRF-Token": csrf},
        json={"reason": "regression detected"},
    )
    assert rollback.status_code == 200
    detail = client.get(f"/api/v1/rules/{rule_set_id}")
    assert detail.status_code == 200
    assert detail.json()["current_version_id"] == published_id

    text_export = client.get(
        f"/api/v1/rules/{rule_set_id}/versions/{published_id}/export",
        params={"format": "txt"},
    )
    assert text_export.status_code == 200
    assert text_export.text == content
    json_export = client.get(
        f"/api/v1/rules/{rule_set_id}/versions/{published_id}/export",
        params={"format": "json"},
    )
    assert json_export.status_code == 200
    bundle = json_export.json()
    bundle["rule_set_key"] = "elite-sports-v7-9-json-copy"
    bundle["rule_set_name"] = "V7.9 JSON Copy"
    json_import = client.post(
        "/api/v1/rules/import",
        headers={"X-CSRF-Token": csrf},
        json={
            "format": "json",
            "filename": "v7.9.json",
            "content": json.dumps(bundle, ensure_ascii=False),
            "publish": False,
        },
    )
    assert json_import.status_code == 201, json_import.text
    assert json_import.json()["created"] is True
    assert json_import.json()["version"]["status"] == "draft"


def test_rule_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/rules").status_code == 401
