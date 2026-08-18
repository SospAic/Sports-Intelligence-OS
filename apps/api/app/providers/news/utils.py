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

# Docker Desktop / transparent proxy DNS can return synthetic non-global
# addresses (for example RFC 2544's 198.18.0.0/15) for public media sites.
# These are the only host families allowed to use the media-download DNS
# compatibility path; arbitrary URLs still go through the full SSRF check.
MEDIA_SOURCE_HOST_SUFFIXES = frozenset(
    {
        "youtube.com",
        "youtube-nocookie.com",
        "youtu.be",
        "tiktok.com",
        "douyin.com",
        "iesdouyin.com",
        "bilibili.com",
        "b23.tv",
        "instagram.com",
        "facebook.com",
        "vimeo.com",
        "twitch.tv",
        "x.com",
        "twitter.com",
    }
)

# Docker Desktop and some transparent proxy DNS implementations can map public
# API hostnames to synthetic RFC 2544 / ULA addresses.  LLM providers need the
# same compatibility path as public media hosts, but the allowlist is kept
# separate and intentionally narrow: arbitrary user-supplied URLs must still
# pass the full DNS-based SSRF check.
LLM_SOURCE_HOST_SUFFIXES = frozenset(
    {
        "api.openai.com",
        "generativelanguage.googleapis.com",
        "api.mistral.ai",
        "api.x.ai",
        "api.groq.com",
        "openrouter.ai",
        "api.together.xyz",
        "api.perplexity.ai",
        "api.cohere.ai",
        "api.deepseek.com",
        "api.moonshot.cn",
        "open.bigmodel.cn",
        "dashscope.aliyuncs.com",
        "ark.cn-beijing.volces.com",
        "spark-api-open.xf-yun.com",
        "api.hunyuan.cloud.tencent.com",
        "qianfan.baidubce.com",
        "api.minimax.chat",
        "api.stepfun.com",
        "ai.360.cn",
    }
)


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


def is_known_media_source(value: str) -> bool:
    """Return whether ``value`` belongs to a supported public media host.

    The check is deliberately suffix-boundary aware so a hostname such as
    ``youtube.com.attacker.example`` is not treated as YouTube.
    """

    normalized = validate_source_url(value)
    host = (urlsplit(normalized).hostname or "").casefold().rstrip(".")
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in MEDIA_SOURCE_HOST_SUFFIXES
    )


def is_known_llm_source(value: str) -> bool:
    """Return whether ``value`` belongs to a built-in public LLM host.

    This is a DNS compatibility allowlist, not an authentication or provider
    capability check.  The suffix boundary prevents lookalike domains such as
    ``api.deepseek.com.attacker.example`` from matching.
    """

    normalized = validate_source_url(value)
    host = (urlsplit(normalized).hostname or "").casefold().rstrip(".")
    return any(
        host == suffix or host.endswith(f".{suffix}") for suffix in LLM_SOURCE_HOST_SUFFIXES
    )


async def ensure_public_media_endpoint(value: str) -> str:
    """Validate a downloader URL without rejecting Docker synthetic DNS.

    Supported media hostnames retain literal-IP, local-hostname, credential,
    and secret-query protections. Only their DNS resolution check is skipped
    because the downloader may run behind a transparent proxy. Unknown hosts
    must resolve exclusively to globally routable addresses.
    """

    normalized = validate_source_url(value)
    return await ensure_public_endpoint(
        normalized,
        skip_dns_check=is_known_media_source(normalized),
    )


async def ensure_public_llm_endpoint(value: str) -> str:
    """Validate a public LLM URL without rejecting Docker synthetic DNS.

    Only the built-in provider hostnames above may skip the runtime DNS
    address check.  Custom OpenAI-compatible endpoints continue to require a
    globally routable DNS result, which preserves the SSRF boundary.
    """

    normalized = validate_source_url(value, allow_secret_query=False)
    return await ensure_public_endpoint(
        normalized,
        allow_secret_query=False,
        skip_dns_check=is_known_llm_source(normalized),
    )


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
