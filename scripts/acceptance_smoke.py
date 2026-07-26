from __future__ import annotations

import argparse
import json
import os
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener


def _http_origin(url: SplitResult) -> tuple[str, str, int | None]:
    if url.scheme not in {"http", "https"}:
        raise ValueError("acceptance URL must use http or https")
    if not url.hostname:
        raise ValueError("acceptance URL must include a hostname")
    if url.username or url.password:
        raise ValueError("acceptance URL must not contain credentials")
    return url.scheme, url.hostname, url.port


def _resolve_request_url(base_url: str, path: str) -> str:
    base = urlsplit(base_url)
    origin = _http_origin(base)
    resolved = urlsplit(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")))
    if _http_origin(resolved) != origin:
        raise ValueError("acceptance request path must remain on the configured origin")
    return resolved.geturl()


def _request(
    opener: object,
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
) -> tuple[int, object]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(  # noqa: S310 - scheme and same-origin policy validated above
        _resolve_request_url(base_url, path),
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    response = opener.open(request, timeout=10)  # type: ignore[attr-defined]
    body = response.read()
    content_type = response.headers.get_content_type()
    return response.status, json.loads(body) if content_type == "application/json" else body


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run authenticated first-delivery smoke checks against a local Compose stack."
    )
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    email = os.getenv("SIO_ACCEPTANCE_EMAIL")
    password = os.getenv("SIO_ACCEPTANCE_PASSWORD")
    if not email or not password:
        print(
            "Set SIO_ACCEPTANCE_EMAIL and SIO_ACCEPTANCE_PASSWORD before running smoke checks.",
            file=sys.stderr,
        )
        return 2

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    checks: list[tuple[str, str]] = [
        ("Web login page", "/login"),
        ("API live health", "/health/live"),
        ("Database and Redis readiness", "/health/ready"),
    ]
    authenticated = [
        ("Current user", "/api/v1/me"),
        ("Platforms", "/api/v1/platforms"),
        ("Accounts", "/api/v1/accounts?page=1&page_size=1"),
        ("News sources", "/api/v1/news/sources?page=1&page_size=1"),
        ("Rules", "/api/v1/rules?page=1&page_size=1"),
        ("Prompts", "/api/v1/prompts?page=1&page_size=1"),
        ("Workflows", "/api/v1/workflows"),
        ("Automations", "/api/v1/automations?page=1&page_size=1"),
        ("Notification providers", "/api/v1/notification-providers"),
    ]
    try:
        for label, path in checks:
            status, _ = _request(opener, args.base_url, path)
            if status != 200:
                raise RuntimeError(f"{label} returned HTTP {status}")
            print(f"PASS  {label}")

        status, _ = _request(
            opener,
            args.base_url,
            "/api/v1/auth/login",
            method="POST",
            payload={"email": email, "password": password},
        )
        if status != 200:
            raise RuntimeError(f"Login returned HTTP {status}")
        print("PASS  Login")
        for label, path in authenticated:
            status, _ = _request(opener, args.base_url, path)
            if status != 200:
                raise RuntimeError(f"{label} returned HTTP {status}")
            print(f"PASS  {label}")
    except (HTTPError, URLError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
