"""Static Compose validation used when Docker CLI is unavailable."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REQUIRED_SERVICES = {"postgres", "redis", "api", "worker", "beat", "web", "proxy"}


def require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"{name} must be a mapping")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "compose_file", type=Path, nargs="?", default=Path("docker-compose.yml")
    )
    args = parser.parse_args()

    compose_text = args.compose_file.read_text(encoding="utf-8")
    document = require_mapping(yaml.safe_load(compose_text), "compose document")
    services = require_mapping(document.get("services"), "services")
    missing = REQUIRED_SERVICES - services.keys()
    if missing:
        raise SystemExit(f"missing Compose services: {sorted(missing)}")

    for service_name in ("postgres", "redis", "api", "web"):
        service = require_mapping(services[service_name], service_name)
        if "healthcheck" not in service:
            raise SystemExit(f"{service_name} must define a healthcheck")

    for service_name in ("worker", "beat"):
        service = require_mapping(services[service_name], service_name)
        if "api" not in require_mapping(
            service.get("depends_on"), f"{service_name}.depends_on"
        ):
            raise SystemExit(f"{service_name} must wait for the API readiness gate")

    if (
        "SIO_BOOTSTRAP_ADMIN_PASSWORD: ${SIO_BOOTSTRAP_ADMIN_PASSWORD:-}"
        not in compose_text
    ):
        raise SystemExit(
            "bootstrap administrator password must default to an empty value"
        )
    env_example_lines = {
        line.strip()
        for line in Path(".env.example").read_text(encoding="utf-8").splitlines()
    }
    if "SIO_BOOTSTRAP_ADMIN_PASSWORD=" not in env_example_lines:
        raise SystemExit(".env.example must document an empty administrator password")

    web_dockerfile = Path("deploy/web.Dockerfile").read_text(encoding="utf-8")
    if "API_INTERNAL_URL=http://api:8000" not in web_dockerfile:
        raise SystemExit(
            "Web image must bake the Compose API hostname into Next.js rewrites"
        )

    volumes = require_mapping(document.get("volumes"), "volumes")
    if not {"postgres_data", "redis_data"}.issubset(volumes):
        raise SystemExit("PostgreSQL and Redis named volumes are required")

    print(
        "Static Compose validation passed for services: " + ", ".join(sorted(services))
    )


if __name__ == "__main__":
    main()
