import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class SessionSecrets:
    token: str
    token_hash: str
    csrf_token: str
    csrf_token_hash: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    return password_hash.verify(password, encoded_hash)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secure_compare_hash(raw_value: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(raw_value), expected_hash)


def create_session_secrets(ttl_seconds: int) -> SessionSecrets:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    return SessionSecrets(
        token=token,
        token_hash=hash_secret(token),
        csrf_token=csrf_token,
        csrf_token_hash=hash_secret(csrf_token),
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
    )


def create_csrf_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_secret(token)
