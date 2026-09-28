"""Password hashing, session tokens, and the current-user dependency."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from sqlalchemy import text

from app.config import Settings, get_settings
from app.db import Database
from app.deps import get_db
from app.schemas import UserOut

_hasher = PasswordHash.recommended()  # argon2id
# Verified against when the email doesn't exist, so response time doesn't reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False
    return _hasher.verify(password, password_hash)


def create_token(user_id: UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=settings.jwt_expire_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def set_session_cookie(response: Response, user_id: UUID, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie,
        create_token(user_id, settings),
        max_age=settings.jwt_expire_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


_UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.")


async def get_current_user(
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserOut:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        raise _UNAUTHORIZED
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise _UNAUTHORIZED from None

    async with db.engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT id, email, created_at FROM users WHERE id = :id"), {"id": user_id})
        ).one_or_none()
    if row is None:  # user was deleted after the token was issued
        raise _UNAUTHORIZED
    return UserOut(**row._mapping)


CurrentUser = Annotated[UserOut, Depends(get_current_user)]
