from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models.subscription import SubscriptionRule
from app.schemas.subscription import SubscriptionEvaluateRequest, SubscriptionRuleCreate
from app.services.subscriptions import SubscriptionService, _safe_facts, _threshold_matches


def _payload(**facts: object) -> SubscriptionEvaluateRequest:
    return SubscriptionEvaluateRequest(
        entity_type="content",
        entity_id=uuid4(),
        event_key="content_snapshot:test",
        facts=facts,
        source_kind="live",
    )


def test_subscription_create_normalizes_keywords_and_requires_channels() -> None:
    payload = SubscriptionRuleCreate(
        name="热点",
        trigger_type="keyword_match",
        keywords=["  NBA  ", "nba", "伤停"],
        channel_ids=[uuid4()],
    )

    assert payload.keywords == ["nba", "伤停"]
    with pytest.raises(ValueError):
        SubscriptionRuleCreate(name="缺少渠道")


def test_subscription_matchers_cover_new_content_keyword_and_metric_spike() -> None:
    new_content = SubscriptionRule(trigger_type="new_content")
    keyword = SubscriptionRule(trigger_type="keyword_match", keywords=["伤停"])
    metric = SubscriptionRule(
        trigger_type="metric_spike", thresholds={"view_count": {"increase": 1000}}
    )

    matched, details = SubscriptionService._match_rule(new_content, _payload(is_new=True))
    assert matched is True
    assert details["reason"] == "new_content"

    matched, details = SubscriptionService._match_rule(
        keyword, _payload(title="赛前伤停更新")
    )
    assert matched is True
    assert details["matched_keywords"] == ["伤停"]

    metric_payload = _payload(view_count=2500)
    metric_payload.previous = {"view_count": 1200}
    matched, details = SubscriptionService._match_rule(metric, metric_payload)
    assert matched is True
    assert details["matched_metrics"]["view_count"]["current"] == 2500.0


def test_subscription_target_and_cooldown_helpers() -> None:
    account_id = uuid4()
    platform_id = uuid4()
    rule = SubscriptionRule(account_id=account_id, platform_id=platform_id)
    payload = _payload(account_id=str(account_id), platform_id=str(platform_id))
    assert SubscriptionService._target_matches(rule, payload)

    payload.facts["platform_id"] = str(uuid4())
    assert not SubscriptionService._target_matches(rule, payload)

    rule.last_triggered_at = datetime.now(UTC)
    rule.cooldown_seconds = 60
    assert SubscriptionService._in_cooldown(rule, datetime.now(UTC))


def test_subscription_threshold_and_notification_fact_allowlist() -> None:
    assert _threshold_matches(2500, 1200, {"increase": 1000})
    assert _threshold_matches(2, 1, {"rate": 1.5})
    assert not _threshold_matches(100, None, {"increase": 1})
    assert _safe_facts({"title": "x", "password": "secret", "view_count": 3}) == {
        "title": "x",
        "view_count": 3,
    }
