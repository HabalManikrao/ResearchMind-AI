"""Authentication endpoints: register, login, current-user (spec §21)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.security.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenOut:
    settings = get_settings()
    token = create_access_token(user.id)
    return TokenOut(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
async def register(body: RegisterIn, request: Request, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    email = body.email.strip().lower()

    existing_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if not settings.registration_open and existing_count > 0:
        raise HTTPException(403, "Registration is closed")

    dupe = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if dupe is not None:
        raise HTTPException(409, "An account with this email already exists")

    user = User(
        email=email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        # The first account created becomes an admin.
        is_admin=(existing_count == 0),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await audit.record("auth.register", user_id=user.id, request=request,
                       detail={"email": email})
    return _token_response(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    email = body.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if user is None or not verify_password(body.password, user.password_hash):
        # Same message for both cases so we don't leak which emails exist.
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "Account is disabled")
    await audit.record("auth.login", user_id=user.id, request=request)
    return _token_response(user)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
