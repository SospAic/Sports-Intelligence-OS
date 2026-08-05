import asyncio
import hashlib
import ipaddress
import re
import socket
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}
SENSITIVE_QUERY_PARTS = ("api_key", "apikey", "access_token", "token", "secret", "password")


def clean_text(value: object, *, limit: int = 100_000) -> str | None:
    if value is None:
        return None
    text = BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)
    normalized = " ".join(text.split())
    return normalized[:limit] if normalized else None


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("article URL must be absolute HTTP(S)")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    path = re.sub(r"/{2,}", "/", parsed.path) or "/"
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path.rstrip("/") or "/",
            urlencode(sorted(query)),
            "",
        )
    )


def validate_source_url(value: str, *, allow_secret_query: bool = False) -> str:
    normalized = canonicalize_url(value)
    parsed = urlsplit(normalized)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("source URL cannot contain embedded credentials")
    if not allow_secret_query and any(
        any(part in key.casefold() for part in SENSITIVE_QUERY_PARTS)
        for key, _item in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        raise ValueError("source URL cannot contain secrets in its query string")
    host = parsed.hostname
    if host is None:
        raise ValueError("source URL has no hostname")
    lowered = host.casefold().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".localhost", ".local")):
        raise ValueError("source URL cannot target a local hostname")
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return normalized
    if not address.is_global:
        raise ValueError("source URL cannot target a non-public IP address")
    return normalized


async def ensure_public_endpoint(
    value: str, *, allow_secret_query: bool = False, skip_dns_check: bool = False
) -> str:
    """Validate both the URL text and every currently resolved address.

    This check is repeated immediately before an outbound request so a hostname
    that resolves to loopback, link-local, or a private network cannot bypass the
    literal-IP validation used when a source is saved.

    Set ``skip_dns_check=True`` in Docker/dev environments where the container DNS
    resolves external hostnames to non-global ranges (e.g. 198.18.0.0/15).
    """

    normalized = validate_source_url(value, allow_secret_query=allow_secret_query)
    if skip_dns_check:
        return normalized
    host = urlsplit(normalized).hostname
    if host is None:
        raise ValueError("source URL has no hostname")
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(
            host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise OSError("source hostname cannot be resolved") from exc
    if not addresses:
        raise OSError("source hostname did not resolve to an address")
    for address in addresses:
        if not ipaddress.ip_address(address[4][0]).is_global:
            raise ValueError("source URL resolved to a non-public IP address")
    return normalized


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def title_similarity(left: str, right: str) -> float:
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0.0
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    left_cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized_left))
    right_cjk = "".join(re.findall(r"[\u3400-\u9fff]", normalized_right))
    cjk_score = 0.0
    if len(left_cjk) >= 2 and len(right_cjk) >= 2:
        left_bigrams = {left_cjk[index : index + 2] for index in range(len(left_cjk) - 1)}
        right_bigrams = {right_cjk[index : index + 2] for index in range(len(right_cjk) - 1)}
        cjk_union = left_bigrams | right_bigrams
        cjk_score = len(left_bigrams & right_bigrams) / len(cjk_union)
    return max(jaccard, sequence, cjk_score)


def article_hash(title: str, canonical_url: str, summary: str | None) -> str:
    # URL has its own exact comparison. Excluding it lets syndicated copies with
    # different publisher URLs share the same content fingerprint.
    material = "\n".join((normalize_title(title), normalize_title(summary or "")))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def nested_value(data: Mapping[str, object], path: str) -> object:
    current: object = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current
