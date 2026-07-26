from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_session_secrets, verify_password
from app.models.session import AuthSession
from app.models.user import User
from app.repositories.users import UserRepository


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
