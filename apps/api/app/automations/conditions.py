from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

TruthValue = Literal[True, False] | None

GROUP_OPERATORS = {"AND", "OR", "NOT"}
LEAF_OPERATORS = {
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "not_contains",
    "regex",
    "changed",
    "increased_by",
    "increased_percent",
    "consecutive_matches",
}
FIELD_ALLOWLISTS: dict[str, set[str]] = {
    "content": {
        "entity_id",
        "view_count",
        "like_count",
        "comment_count",
        "share_count",
        "favorite_count",
        "view_growth_1h",
        "view_growth_6h",
        "view_growth_24h",
        "engagement_rate",
        "share_rate",
        "favorite_rate",
        "view_velocity",
        "view_acceleration",
        "viral_score",
        "source_kind",
        "platform_key",
        "title",
    },
    "account": {
        "entity_id",
        "follower_count",
        "following_count",
        "total_like_count",
        "total_view_count",
        "video_count",
        "follower_growth_24h",
        "engagement_rate",
        "source_kind",
        "platform_key",
    },
    "news": {
        "entity_id",
        "heat_score",
        "source_count",
        "article_count",
        "reliability_score",
        "controversy_score",
        "visual_score",
        "story_score",
        "sport",
        "league",
        "status",
        "source_kind",
    },
    "topic_event": {
        "entity_id",
        "heat_score",
        "source_count",
        "article_count",
        "reliability_score",
        "controversy_score",
        "visual_score",
        "story_score",
        "sport",
        "league",
        "status",
        "source_kind",
    },
}


class ConditionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ConditionResult:
    value: TruthValue
    explanation: dict[str, Any]

    @property
    def matched(self) -> bool:
        return self.value is True


def _nested_value(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_condition_tree(
    tree: Mapping[str, Any],
    entity_type: str,
    *,
    max_depth: int = 8,
    max_nodes: int = 100,
) -> None:
    allowed_fields = FIELD_ALLOWLISTS.get(entity_type)
    if allowed_fields is None:
        raise ConditionValidationError(f"unsupported entity_type: {entity_type}")
    seen_nodes = 0

    def visit(node: object, depth: int) -> None:
        nonlocal seen_nodes
        seen_nodes += 1
        if seen_nodes > max_nodes:
            raise ConditionValidationError(f"condition tree exceeds {max_nodes} nodes")
        if depth > max_depth:
            raise ConditionValidationError(f"condition tree exceeds depth {max_depth}")
        if not isinstance(node, Mapping):
            raise ConditionValidationError("each condition node must be an object")
        operator = node.get("operator")
        if operator in GROUP_OPERATORS:
            conditions = node.get("conditions")
            if not isinstance(conditions, list):
                raise ConditionValidationError("group conditions must be an array")
            if operator == "NOT" and len(conditions) != 1:
                raise ConditionValidationError("NOT must contain exactly one condition")
            if operator != "NOT" and not conditions:
                raise ConditionValidationError(f"{operator} must contain at least one condition")
            for child in conditions:
                visit(child, depth + 1)
            return
        if operator not in LEAF_OPERATORS:
            raise ConditionValidationError(f"unsupported condition operator: {operator}")
        field = node.get("field")
        if not isinstance(field, str) or field not in allowed_fields:
            raise ConditionValidationError(f"field is not allowed for {entity_type}: {field}")
        if operator not in {"changed"} and "value" not in node:
            raise ConditionValidationError(f"operator {operator} requires value")
        value = node.get("value")
        if operator in {"in", "not_in"} and (not isinstance(value, list) or len(value) > 100):
            raise ConditionValidationError(
                f"operator {operator} requires an array of up to 100 values"
            )
        if operator in {
            "increased_by",
            "increased_percent",
            "consecutive_matches",
        } and not _is_number(value):
            raise ConditionValidationError(f"operator {operator} requires a finite numeric value")
        if operator == "consecutive_matches" and (not isinstance(value, int) or value < 1):
            raise ConditionValidationError("consecutive_matches requires a positive integer")
        if operator == "regex":
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ConditionValidationError(
                    "regex must be a non-empty string up to 256 characters"
                )
            high_risk = (
                r"\\[1-9]|\(\?[=!<]|(?:\*|\+|\{\d+,?\d*\}){2}"
                r"|\([^)]*(?:\*|\+|\{\d+,?\d*\})[^)]*\)(?:\*|\+|\{\d+,?\d*\})"
                r"|\([^)]*\|[^)]*\)(?:\*|\+|\{\d+,?\d*\})"
            )
            if re.search(high_risk, value):
                raise ConditionValidationError("regex contains unsupported high-risk constructs")
            try:
                re.compile(value)
            except re.error as exc:
                raise ConditionValidationError(f"invalid regex: {exc}") from exc

    visit(tree, 1)


def evaluate_condition_tree(
    tree: Mapping[str, Any],
    facts: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    consecutive_count: int = 0,
) -> ConditionResult:
    previous_facts = previous or {}

    def evaluate(node: Mapping[str, Any]) -> ConditionResult:
        operator = str(node["operator"])
        if operator in GROUP_OPERATORS:
            children = [evaluate(child) for child in node["conditions"]]
            child_values = [child.value for child in children]
            if operator == "AND":
                value: TruthValue = (
                    False if False in child_values else None if None in child_values else True
                )
            elif operator == "OR":
                value = True if True in child_values else None if None in child_values else False
            else:
                value = None if child_values[0] is None else not child_values[0]
            return ConditionResult(
                value=value,
                explanation={
                    "operator": operator,
                    "result": value,
                    "conditions": [child.explanation for child in children],
                },
            )

        field = str(node["field"])
        actual = _nested_value(facts, field)
        old = _nested_value(previous_facts, field)
        expected = node.get("value")
        value = _evaluate_leaf(operator, actual, expected, old, consecutive_count)
        return ConditionResult(
            value=value,
            explanation={
                "field": field,
                "operator": operator,
                "expected": expected,
                "actual": actual,
                "previous": old,
                "result": value,
                "reason": "missing_or_incompatible_value" if value is None else None,
            },
        )

    return evaluate(tree)


def _evaluate_leaf(
    operator: str,
    actual: Any,
    expected: Any,
    previous: Any,
    consecutive_count: int,
) -> TruthValue:
    if operator == "changed":
        return None if actual is None or previous is None else actual != previous
    if operator in {"increased_by", "increased_percent"}:
        if not _is_number(actual) or not _is_number(previous) or not _is_number(expected):
            return None
        increase = actual - previous
        if operator == "increased_by":
            return bool(increase >= expected)
        if previous == 0:
            return None
        return bool((increase / abs(previous)) * 100 >= expected)
    if operator == "consecutive_matches":
        if not isinstance(expected, int) or actual is None:
            return None
        return bool(actual) and consecutive_count + 1 >= expected
    if actual is None:
        return None
    if operator == "eq":
        return bool(actual == expected)
    if operator == "ne":
        return bool(actual != expected)
    if operator in {"gt", "gte", "lt", "lte"}:
        if not _is_number(actual) or not _is_number(expected):
            return None
        if operator == "gt":
            return bool(actual > expected)
        if operator == "gte":
            return bool(actual >= expected)
        if operator == "lt":
            return bool(actual < expected)
        return bool(actual <= expected)
    if operator in {"in", "not_in"}:
        if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes)):
            return None
        contained = actual in expected
        return contained if operator == "in" else not contained
    if operator in {"contains", "not_contains"}:
        if not isinstance(actual, (str, Sequence, Mapping)):
            return None
        try:
            contained = expected in actual
        except TypeError:
            return None
        return contained if operator == "contains" else not contained
    if operator == "regex":
        if not isinstance(actual, str) or not isinstance(expected, str):
            return None
        return re.search(expected, actual[:10_000]) is not None
    return None
