from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*}}")
SENSITIVE_KEY = re.compile(r"(api[_-]?key|token|secret|password|authorization|cookie)", re.I)


class PromptRenderError(ValueError):
    pass


def validate_variables(schema: Mapping[str, Any], variables: Mapping[str, Any]) -> None:
    required = schema.get("required", [])
    if isinstance(required, list):
        missing = [key for key in required if key not in variables]
        if missing:
            raise PromptRenderError(f"Missing prompt variables: {', '.join(map(str, missing))}")
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False and isinstance(properties, dict):
        unknown = set(variables) - set(properties)
        if unknown:
            raise PromptRenderError(f"Unknown prompt variables: {', '.join(sorted(unknown))}")


def _resolve(variables: Mapping[str, Any], path: str) -> Any:
    value: Any = variables
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise PromptRenderError(f"Missing prompt variable: {path}")
        value = value[part]
    return value


def render_prompt(template: str, schema: Mapping[str, Any], variables: Mapping[str, Any]) -> str:
    validate_variables(schema, variables)

    def replace(match: re.Match[str]) -> str:
        value = _resolve(variables, match.group(1))
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    rendered = PLACEHOLDER.sub(replace, template)
    unresolved = PLACEHOLDER.findall(rendered)
    if unresolved:
        raise PromptRenderError(f"Unresolved prompt variables: {', '.join(unresolved)}")
    return rendered


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "***REDACTED***" if SENSITIVE_KEY.search(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value
