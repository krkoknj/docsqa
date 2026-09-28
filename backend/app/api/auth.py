from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import CurrentUser, clear_session_cookie, hash_password, set_session_cookie, verify_password
from app.config import Settings, get_settings
from app.db import Database
from app.deps import get_db
from app.schemas import Credentials, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])

DbDep = Annotated[Database, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(body: Credentials, response: Response, db: DbDep, settings: SettingsDep):
    try:
        async with db.engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :hash) "
                        "RETURNING id, email, created_at"
                    ),
                    {"id": uuid4(), "email": body.email.lower(), "hash": hash_password(body.password)},
                )
            ).one()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 가입된 이메일입니다.") from None
    user = UserOut(**row._mapping)
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/login", response_model=UserOut)
async def login(body: Credentials, response: Response, db: DbDep, settings: SettingsDep):
    async with db.engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT id, email, created_at, password_hash FROM users WHERE lower(email) = :email"),
                {"email": body.email.lower()},
            )
        ).one_or_none()
    if not verify_password(body.password, row.password_hash if row else None):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
    user = UserOut(id=row.id, email=row.email, created_at=row.created_at)
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, settings: SettingsDep):
    clear_session_cookie(response, settings)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
