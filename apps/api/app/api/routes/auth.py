from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response

from app.api.dependencies import CsrfProtectedAuth, CurrentAuth, DatabaseSession
from app.core.security import create_csrf_token
from app.models.user import User
from app.schemas.auth import AuthResponse, CsrfResponse, LoginRequest, UserSummary
from app.services.auth import (
    authenticate_user,
    check_login_rate_limit,
    create_auth_session,
    record_login_attempt,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def to_user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email_display,
        display_name=user.display_name,
        locale=user.locale,
        timezone=user.timezone,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> AuthResponse:
    settings = request.app.state.settings
    remote_address = request.client.host if request.client else "unknown"
    rate_limit = await check_login_rate_limit(db, str(payload.email), remote_address, settings)
    if not rate_limit.allowed:
        raise HTTPException(
            status_code=429,
            headers={"Retry-After": str(rate_limit.retry_after_seconds)},
            detail={
                "code": "login_rate_limited",
                "detail": "登录尝试过于频繁，请稍后重试",
            },
        )
    user = await authenticate_user(db, str(payload.email), payload.password)
    if user is None:
        record_login_attempt(db, rate_limit, succeeded=False)
        await db.commit()
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "detail": "邮箱或密码错误"},
        )

    auth_session, raw_token, csrf_token = create_auth_session(user, settings)
    record_login_attempt(db, rate_limit, succeeded=True)
    auth_session.user_agent_summary = request.headers.get("user-agent", "")[:255] or None
    db.add(auth_session)
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        max_age=settings.session_ttl_seconds,
        expires=auth_session.expires_at,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return AuthResponse(
        user=to_user_summary(user),
        csrf_token=csrf_token,
        expires_at=auth_session.expires_at,
    )


@router.get("/csrf", response_model=CsrfResponse)
async def rotate_csrf(auth: CurrentAuth, db: DatabaseSession) -> CsrfResponse:
    raw_token, token_hash = create_csrf_token()
    auth.session.csrf_token_hash = token_hash
    await db.commit()
    return CsrfResponse(csrf_token=raw_token)


@router.post("/logout", status_code=204)
async def logout(
    auth: CsrfProtectedAuth,
    request: Request,
    response: Response,
    db: DatabaseSession,
) -> None:
    auth.session.revoked_at = datetime.now(UTC)
    await db.commit()
    response.delete_cookie(
        request.app.state.settings.session_cookie_name,
        path="/",
        secure=request.app.state.settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
