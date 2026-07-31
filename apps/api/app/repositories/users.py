from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import normalize_email
from app.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email_normalized == normalize_email(email))
        )
        return result.scalar_one_or_none()

    def add(self, user: User) -> None:
        self._session.add(user)
