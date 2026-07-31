import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_session_secrets, normalize_email, verify_password
from app.models.session import AuthSession, LoginAttempt
from app.models.user import User
from app.repositories.users import UserRepository


@dataclass(frozen=True)
class LoginRateLimitResult:
    allowed: bool
    identity_hash: str
    ip_hash: str
    retry_after_seconds: int


def security_fingerprint(value: str, settings: Settings) -> str:
    key = settings.secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


async def check_login_rate_limit(
    session: AsyncSession,
    email: str,
    remote_address: str,
    settings: Settings,
) -> LoginRateLimitResult:
    identity_hash = security_fingerprint(f"identity:{normalize_email(email)}", settings)
    ip_hash = security_fingerprint(f"ip:{remote_address or 'unknown'}", settings)
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.auth_login_window_seconds)
    base_filters = (LoginAttempt.succeeded.is_(False), LoginAttempt.attempted_at >= cutoff)
    identity_count = int(
        await session.scalar(
            select(func.count(LoginAttempt.id)).where(
                *base_filters, LoginAttempt.identity_hash == identity_hash
            )
        )
        or 0
    )
    ip_count = int(
        await session.scalar(
            select(func.count(LoginAttempt.id)).where(
                *base_filters, LoginAttempt.ip_hash == ip_hash
            )
        )
        or 0
    )
    allowed = (
        identity_count < settings.auth_login_max_attempts_per_identity
        and ip_count < settings.auth_login_max_attempts_per_ip
    )
    return LoginRateLimitResult(
        allowed=allowed,
        identity_hash=identity_hash,
        ip_hash=ip_hash,
        retry_after_seconds=settings.auth_login_window_seconds,
    )


def record_login_attempt(
    session: AsyncSession,
    decision: LoginRateLimitResult,
    *,
    succeeded: bool,
) -> None:
    session.add(
        LoginAttempt(
            identity_hash=decision.identity_hash,
            ip_hash=decision.ip_hash,
            attempted_at=datetime.now(UTC),
            succeeded=succeeded,
        )
    )


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    user = await UserRepository(session).get_by_email(email)
    if user is None:
        # Spend Argon2 work on unknown users to reduce account-enumeration timing signals.
        from app.core.security import hash_password

        hash_password(password)
        return None
    if user.status != "active" or not verify_password(password, user.password_hash):
        return None
    return user


def create_auth_session(user: User, settings: Settings) -> tuple[AuthSession, str, str]:
    secrets = create_session_secrets(settings.session_ttl_seconds)
    now = datetime.now(UTC)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=secrets.token_hash,
        csrf_token_hash=secrets.csrf_token_hash,
        created_at=now,
        last_seen_at=now,
        expires_at=secrets.expires_at,
        revoked_at=None,
        ip_hash=None,
        user_agent_summary=None,
    )
    return auth_session, secrets.token, secrets.csrf_token
