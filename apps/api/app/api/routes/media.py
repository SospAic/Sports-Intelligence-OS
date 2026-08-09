"""Serve locally-archived media (thumbnail / video / subtitles / info-json).

Files are written by download-capable adapters under ``MEDIA_ROOT`` during a
sync and referenced from ``ContentItem.media``. This endpoint resolves a stored
*relative* path, enforces workspace ownership, and guards against path
traversal before streaming the bytes back to the detail page.
"""

from __future__ import annotations

import functools
import hashlib
import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import anyio
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.dependencies import CurrentAuth, DatabaseSession
from app.models.monitoring import Account, ContentItem

router = APIRouter(tags=["media"])

#: Default media root; overridable per deployment via the SIO_MEDIA_ROOT env var.
MEDIA_ROOT = os.environ.get("SIO_MEDIA_ROOT", "/workspace/media")

_EXT_CONTENT_TYPE: dict[str, str] = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".flv": "video/x-flv",
    ".m4v": "video/mp4",
    ".avi": "video/x-msvideo",
    ".vtt": "text/vtt",
    ".srt": "application/x-subrip",
    ".ass": "text/x-ssa",
    ".sbv": "text/plain",
    ".lrc": "text/plain",
    ".json": "application/json",
}


def _allowed_files(media: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for key in ("thumbnail", "video", "info_json"):
        value = media.get(key)
        if isinstance(value, str) and value:
            allowed.add(value)
    for sub in media.get("subtitles") or []:
        if isinstance(sub, dict) and sub.get("file"):
            allowed.add(sub["file"])
    return allowed


def _safe_media_path(base: str, file: str) -> str | None:
    """Resolve a stored relative path to an absolute file, guarding traversal.

    Returns ``None`` when the joined path escapes ``MEDIA_ROOT``.
    """
    candidate = os.path.normpath(os.path.join(MEDIA_ROOT, base, file))
    root = os.path.normpath(MEDIA_ROOT)
    if candidate != root and not candidate.startswith(root + os.sep):
        return None
    return candidate


@router.get("/media/{content_id}/{file}")
async def serve_content_media(
    content_id: UUID,
    file: str,
    auth: CurrentAuth,
    db: DatabaseSession,
) -> FileResponse:
    # Media is referenced from <img>/<video> tags, which cannot send the
    # X-Workspace-Id header, so we authenticate the user and assert the content
    # belongs to one of their active workspaces rather than relying on the
    # header. The unguessable content UUID is the only capability needed.
    member_workspace_ids = {
        membership.workspace_id
        for membership in auth.user.memberships
        if membership.status == "active"
        and getattr(membership.workspace, "status", "active") == "active"
    }
    content = await db.scalar(select(ContentItem).where(ContentItem.id == content_id))
    if content is None or content.workspace_id not in member_workspace_ids:
        raise HTTPException(status_code=404, detail="media not found")
    media = content.media
    if not isinstance(media, dict):
        raise HTTPException(status_code=404, detail="media not found")

    # The requested filename must be one we explicitly recorded for this
    # content — never an arbitrary path — to avoid serving stray files.
    if file not in _allowed_files(media):
        raise HTTPException(status_code=404, detail="media not found")

    base = media.get("base")
    if not isinstance(base, str) or not base:
        raise HTTPException(status_code=404, detail="media not found")

    candidate = _safe_media_path(base, file)
    if candidate is None:
        raise HTTPException(status_code=400, detail="invalid media path")

    if not await anyio.to_thread.run_sync(os.path.isfile, candidate):
        raise HTTPException(status_code=404, detail="media file missing")

    ext = os.path.splitext(file)[1].lower()
    media_type = _EXT_CONTENT_TYPE.get(ext, "application/octet-stream")
    return FileResponse(candidate, media_type=media_type, filename=file)


# --- Account avatar local archive ---------------------------------------
#
# Platform avatars (especially TikTok / Douyin) are served through short-lived
# signed CDN URLs that 404 within hours, so the account list / detail pages
# render broken images. Instead of hot-linking the remote URL, we lazily cache
# the avatar on first request under ``MEDIA_ROOT/avatars`` and serve the
# permanent local copy thereafter. A miss (no avatar, or a failed fetch) returns
# 404 so the frontend can fall back to the remote URL and finally to initials.

_AVATAR_ALLOWED_EXT: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
_AVATAR_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# Networks whose addresses must never be fetched for an avatar (SSRF guard).
# NOTE: we deliberately do NOT reject every non-global address. Inside the
# proxied / containerised runtime the DNS resolver rewrites *all* public CDN
# hostnames to a private-looking egress address (e.g. 198.18.0.0/15, the RFC
# 2544 benchmarking range, or the fdfe:dcba:9876::/48 documentation prefix used
# by the egress proxy). Rejecting those blocks every legitimate avatar, which
# is exactly why cached avatars were always empty before. We therefore only
# block addresses that are genuinely internal / infrastructure. The proxy
# egress ranges are explicitly allow-listed so real CDN images can be fetched.
_PROXY_EGRESS_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("fdfe:dcba:9876::/48"),
)
_DANGEROUS_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. cloud metadata 169.254.169.254
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("10.0.0.0/8"),  # RFC1918
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),  # unique-local (ULA)
)


def _avatar_cache_path(account_id: UUID, avatar_url: str) -> str:
    parsed = urlparse(avatar_url)
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext not in _AVATAR_ALLOWED_EXT:
        ext = ".jpg"
    # Hash the URL into the cache filename so a changed remote avatar (same
    # extension) invalidates the previously cached, now-wrong local copy.
    # Previously the key was account_id + extension only, so an account whose
    # avatar URL changed but kept the same extension would keep serving the
    # stale image indefinitely.
    url_hash = hashlib.sha256(avatar_url.encode("utf-8")).hexdigest()[:16]
    return os.path.join(MEDIA_ROOT, "avatars", f"{account_id}-{url_hash}{ext}")


def _is_safe_avatar_url(url: str) -> None:
    """Reject avatar URLs that resolve to internal / metadata addresses (SSRF).

    We block loopback, link-local (incl. 169.254.169.254 cloud metadata),
    RFC1918 and ULA ranges. Redirects are not followed, so a public hostname
    cannot 30x to an internal one. The egress-proxy ranges (see
    ``_PROXY_EGRESS_NETWORKS``) are explicitly allow-listed because the runtime
    DNS rewrites every public CDN hostname to those private-looking addresses;
    rejecting them would block all legitimate avatars.
    """

    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("avatar URL must use http or https")
    hostname = (parsed.hostname or "").strip().lower()
    # These literals are an SSRF *denylist*, not a bind address.
    if hostname in {"localhost", "0.0.0.0", "::1", "::", ""}:  # noqa: S104
        raise ValueError("avatar host is not allowed")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"avatar host unresolved: {hostname}") from exc
    for info in infos:
        addr = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        # Egress proxy rewrites public hostnames to these ranges — safe to fetch.
        if any(ip in net for net in _PROXY_EGRESS_NETWORKS):
            continue
        if ip.is_loopback or ip.is_multicast:
            raise ValueError("avatar host resolves to a loopback/multicast address")
        if any(ip in net for net in _DANGEROUS_NETWORKS):
            raise ValueError("avatar host resolves to a non-public address")


# Maximum bytes we will cache for an avatar. Avatars are tiny (< 2 MB); this is
# a hard ceiling so a misbehaving CDN / login-wall HTML page can never fill the
# media volume. 10 MB gives generous headroom.
_AVATAR_MAX_BYTES = 10 * 1024 * 1024


def _fetch_remote_bytes(url: str, timeout: int = 10) -> bytes:
    _is_safe_avatar_url(url)
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    # CDNs (YouTube / TikTok / Douyin) reject bare server-side requests and
    # return 400/403/404 unless a browser-like Referer + Accept header is sent.
    # A same-origin Referer is enough for all three platforms.
    headers = {
        "User-Agent": _AVATAR_USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/png,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": origin,
    }
    with httpx.Client(
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        # D: a login wall / error page is served as text/html, not an image.
        # Reject non-image content up front so we never cache HTML as an avatar.
        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.lower().startswith("image/"):
            raise ValueError(f"avatar source is not an image: {content_type}")
        # Reject oversized responses before reading the body (content-length is
        # advisory, so the actual length is re-checked below).
        declared = response.headers.get("content-length")
        if declared and int(declared) > _AVATAR_MAX_BYTES:
            raise ValueError("avatar source exceeds maximum size")
        data = response.content
        if len(data) > _AVATAR_MAX_BYTES:
            raise ValueError("avatar source exceeds maximum size")
        return data


def _write_file(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


def cache_avatar_for_account(account_id: UUID, avatar_url: str | None) -> bool:
    """Best-effort download + persist an account avatar at sync time so the
    local copy survives CDN URL expiry (TikTok / Douyin sign their avatar URLs,
    which 404 within hours). Returns True when a local copy was written.

    Safe to call from the worker: failing fetches (expired signature, blocked
    CDN) degrade to False and the ``/accounts/{id}/avatar`` endpoint later falls
    back to the remote URL, then to initials.
    """
    if not avatar_url:
        return False
    # Skip re-download when a local copy already exists for this exact URL.
    cache_path = _avatar_cache_path(account_id, avatar_url)
    if os.path.isfile(cache_path):
        return True
    try:
        data = _fetch_remote_bytes(avatar_url)
    except Exception:  # noqa: BLE001 - avatar caching is never fatal
        return False
    if not data:
        return False
    cache_path = _avatar_cache_path(account_id, avatar_url)
    avatars_dir = os.path.dirname(cache_path)
    os.makedirs(avatars_dir, 0o755, exist_ok=True)
    _write_file(cache_path, data)
    return True


@router.get("/accounts/{account_id}/avatar")
async def serve_account_avatar(
    account_id: UUID,
    auth: CurrentAuth,
    db: DatabaseSession,
) -> FileResponse:
    member_workspace_ids = {
        membership.workspace_id
        for membership in auth.user.memberships
        if membership.status == "active"
        and getattr(membership.workspace, "status", "active") == "active"
    }
    account = await db.scalar(select(Account).where(Account.id == account_id))
    if account is None or account.workspace_id not in member_workspace_ids:
        raise HTTPException(status_code=404, detail="avatar not found")
    avatar_url = account.avatar_url
    if not avatar_url:
        raise HTTPException(status_code=404, detail="avatar not found")

    cache_path = _avatar_cache_path(account_id, avatar_url)
    if await anyio.to_thread.run_sync(os.path.isfile, cache_path):
        ext = os.path.splitext(cache_path)[1].lower()
        return FileResponse(
            cache_path,
            media_type=_EXT_CONTENT_TYPE.get(ext, "image/jpeg"),
            filename=os.path.basename(cache_path),
        )
    try:
        data = await anyio.to_thread.run_sync(_fetch_remote_bytes, avatar_url)
    except Exception as exc:  # noqa: BLE001 - any fetch failure degrades to remote URL
        raise HTTPException(status_code=404, detail="avatar not found") from exc
    if not data:
        raise HTTPException(status_code=404, detail="avatar not found")
    avatars_dir = os.path.dirname(cache_path)
    await anyio.to_thread.run_sync(functools.partial(os.makedirs, avatars_dir, 0o755, True))
    await anyio.to_thread.run_sync(functools.partial(_write_file, cache_path, data))
    ext = os.path.splitext(cache_path)[1].lower()
    return FileResponse(
        cache_path,
        media_type=_EXT_CONTENT_TYPE.get(ext, "image/jpeg"),
        filename=os.path.basename(cache_path),
    )
