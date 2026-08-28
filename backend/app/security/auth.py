"""Authentication: password hashing, JWT issuing/verification, and the
`get_current_user` dependency used to protect endpoints (spec §21).

When ``settings.auth_enabled`` is False the API runs as a single shared local
account (no token required) — convenient for a personal offline deployment. When
True, a valid ``Authorization: Bearer <jwt>`` is required on protected routes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User

# A synthetic id used for the shared account when auth is disabled. Projects
# created in that mode carry this owner so ownership checks stay consistent.
LOCAL_USER_ID = "local"

# auto_error=False so we can decide 401 vs. anonymous ourselves (and support the
# auth-disabled mode where no header is present).
_bearer = HTTPBearer(auto_error=False)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    # bcrypt hashes at most 72 bytes; encode then truncate defensively.
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:72], password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# Tokens
# --------------------------------------------------------------------------- #
def create_access_token(user_id: str, *, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    minutes = settings.jwt_expire_minutes if expires_minutes is None else expires_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> str:
    """Return the subject (user id) or raise 401 on any problem."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        raise _CREDENTIALS_EXC
    sub = payload.get("sub")
    if not sub:
        raise _CREDENTIALS_EXC
    return sub


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
def _local_user() -> User:
    """The shared account used when auth is disabled (not persisted)."""
    return User(
        id=LOCAL_USER_ID, email="local@localhost", name="Local User",
        password_hash="", is_active=True,
    )


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    settings = get_settings()
    if not settings.auth_enabled:
        return _local_user()
    if creds is None or not creds.credentials:
        raise _CREDENTIALS_EXC
    user_id = decode_token(creds.credentials)
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalars().first()
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user
