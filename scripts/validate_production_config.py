"""Fail-fast production configuration and image-pinning gate.

This check is intentionally dependency-free so it can run before Python
packages, Docker, or the database are available. It validates the deployment
contract; it does not contact third-party services and cannot replace a real
backup/restore or platform canary.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DEVELOPMENT_SECRET = "local-development-secret-replace-before-production-2026"
DEVELOPMENT_PASSWORD = "sio-local-development-only"
SHA256_REFERENCE = re.compile(r"@sha256:[0-9a-f]{64}$", re.IGNORECASE)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def main() -> int:
    if os.environ.get("SIO_ENVIRONMENT", "development").casefold() != "production":
        print("Production configuration gate skipped: SIO_ENVIRONMENT is not production.")
        return 0

    errors: list[str] = []
    secret = os.environ.get("SIO_SECRET_KEY", "")
    database_url = os.environ.get("SIO_DATABASE_URL", "")
    notification_key = os.environ.get("SIO_NOTIFICATION_ENCRYPTION_KEY", "")
    if len(secret) < 32 or secret == DEVELOPMENT_SECRET:
        errors.append("SIO_SECRET_KEY must be unique and at least 32 characters")
    if DEVELOPMENT_PASSWORD in database_url:
        errors.append("SIO_DATABASE_URL must not use the development password")
    if not _bool("SIO_SESSION_COOKIE_SECURE"):
        errors.append("SIO_SESSION_COOKIE_SECURE=true is required")
    if len(notification_key) < 32:
        errors.append("SIO_NOTIFICATION_ENCRYPTION_KEY must be unique and at least 32 characters")
    if os.environ.get("SIO_LLM_FALLBACK_BASE_URL", "").strip():
        errors.append("SIO_LLM_FALLBACK_BASE_URL must be empty in production")
    allowlist = os.environ.get("SIO_LLM_INTERNAL_HOSTS_ALLOWLIST", "")
    if "llm-experimental" in allowlist:
        errors.append("SIO_LLM_INTERNAL_HOSTS_ALLOWLIST must exclude llm-experimental")
    if _bool("SIO_MEDIA_LIFECYCLE_ENABLED") and not os.environ.get(
        "SIO_MEDIA_STORAGE_QUOTA_BYTES", ""
    ).strip():
        errors.append("media lifecycle cleanup requires SIO_MEDIA_STORAGE_QUOTA_BYTES")

    image = os.environ.get("SIO_TRANSLATION_IMAGE", "")
    if image and not SHA256_REFERENCE.search(image):
        errors.append("SIO_TRANSLATION_IMAGE must use an immutable @sha256 digest")
    compose = Path("docker-compose.yml")
    if compose.exists() and "libretranslate/libretranslate:latest" in compose.read_text(
        encoding="utf-8"
    ):
        errors.append("docker-compose.yml must not use the floating LibreTranslate latest tag")

    if errors:
        print("Production configuration gate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Production configuration gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
