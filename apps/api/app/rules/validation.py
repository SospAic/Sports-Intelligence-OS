from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    rule_key: str | None = None


def validate_rules(rules: Sequence[Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    keys: set[str] = set()
    duplicates: set[str] = set()
    for rule in rules:
        if rule.key in keys:
            duplicates.add(rule.key)
        keys.add(rule.key)
        if not rule.key.strip() or not rule.title.strip() or not rule.instruction.strip():
            issues.append(
                ValidationIssue("error", "required_field_missing", "规则必填字段缺失", rule.key)
            )
        if rule.section_id is None:
            issues.append(ValidationIssue("error", "missing_section", "规则没有所属章节", rule.key))
        if rule.source_status == "unresolved" or not rule.source_reference:
            issues.append(
                ValidationIssue("error", "unresolved_source", "规则无法追溯到原文", rule.key)
            )
        if not rule.qa_check:
            issues.append(
                ValidationIssue("warning", "missing_qa", "规则缺少独立 QA 检查", rule.key)
            )
        if rule.is_mandatory and not rule.enabled:
            issues.append(
                ValidationIssue("error", "mandatory_rule_disabled", "强制规则不能被禁用", rule.key)
            )
    for key in sorted(duplicates):
        issues.append(ValidationIssue("error", "duplicate_key", "规则 key 重复", key))

    by_key = {rule.key: rule for rule in rules}
    active_conflicts: set[tuple[str, str]] = set()
    adjacency: dict[str, list[str]] = {}
    for rule in rules:
        invalid_dependencies = sorted(set(rule.dependencies) - keys)
        invalid_conflicts = sorted(set(rule.conflicts) - keys)
        for dependency in invalid_dependencies:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_dependency",
                    f"依赖规则不存在：{dependency}",
                    rule.key,
                )
            )
        for conflict in invalid_conflicts:
            issues.append(
                ValidationIssue(
                    "error", "invalid_conflict", f"冲突规则不存在：{conflict}", rule.key
                )
            )
        overlap = sorted(set(rule.dependencies) & set(rule.conflicts))
        for target in overlap:
            issues.append(
                ValidationIssue(
                    "error",
                    "dependency_conflict_overlap",
                    f"同一规则不能既依赖又冲突：{target}",
                    rule.key,
                )
            )
        for target in rule.conflicts:
            pair = tuple(sorted((rule.key, target)))
            target_rule = by_key.get(target)
            if (
                target_rule is not None
                and rule.enabled
                and target_rule.enabled
                and pair not in active_conflicts
            ):
                active_conflicts.add(pair)
                issues.append(
                    ValidationIssue(
                        "error",
                        "active_rule_conflict",
                        f"互相冲突的规则同时启用：{pair[0]} / {pair[1]}",
                        rule.key,
                    )
                )
        adjacency[rule.key] = [item for item in rule.dependencies if item in keys]

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str, path: list[str]) -> None:
        if key in visited:
            return
        if key in visiting:
            cycle = path[path.index(key) :] + [key]
            issues.append(
                ValidationIssue(
                    "error",
                    "cyclic_dependency",
                    "检测到循环依赖：" + " -> ".join(cycle),
                    key,
                )
            )
            return
        visiting.add(key)
        for dependency in adjacency.get(key, []):
            visit(dependency, [*path, dependency])
        visiting.remove(key)
        visited.add(key)

    for key in sorted(keys):
        visit(key, [key])
    return issues
