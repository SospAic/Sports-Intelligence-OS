import pytest
from pydantic import ValidationError

from app.core.config import DEVELOPMENT_SECRET, Settings
from app.core.security import hash_password, verify_password


def test_password_hash_is_not_plaintext() -> None:
    raw_password = "correct-horse-battery-staple"  # noqa: S105 - test fixture only
    encoded = hash_password(raw_password)
    assert encoded != raw_password
    assert raw_password not in encoded
    assert verify_password(raw_password, encoded)
    assert not verify_password("incorrect-password", encoded)


def test_production_rejects_development_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            secret_key=DEVELOPMENT_SECRET,
            session_cookie_secure=False,
        )
