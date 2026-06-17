"""Authentication — signup, login, and the current-user dependency.

Real, working auth: passwords are bcrypt-hashed (never stored in clear), and a
successful login issues a signed JWT the frontend stores and replays as a
``Bearer`` token. The JWT secret comes from the ``JWT_SECRET`` env var; if it's
absent we fall back to a process-stable random secret (fine for a single-instance
demo — tokens just don't survive a restart, and we log a one-line notice).

The app is intentionally *not* gated behind auth: ``get_current_user`` is an
optional dependency that returns ``None`` for anonymous requests rather than
raising, so the research UI keeps working without a login. Endpoints that truly
require a user use ``require_user``.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session
from db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# Secret resolution: prefer the env var. In production (DEEPFIELD_ENV=production)
# a missing JWT_SECRET is a hard error — without a stable secret every restart
# would silently invalidate all sessions. In development we fall back to a
# per-process random secret and just log a notice.
_JWT_SECRET = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    if os.getenv("DEEPFIELD_ENV", "development").lower() == "production":
        raise RuntimeError(
            "JWT_SECRET must be set in production. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
            "and set it as an environment variable."
        )
    _JWT_SECRET = secrets.token_urlsafe(48)
    print(  # pragma: no cover - startup notice only
        "[auth] JWT_SECRET not set — using an ephemeral per-process secret. "
        "Set JWT_SECRET for tokens that survive restarts."
    )


# ---- Password hashing (bcrypt, 72-byte input cap) --------------------------

def hash_password(password: str) -> str:
    # bcrypt only considers the first 72 bytes; encode then hash.
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8")[:72], password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):  # malformed stored hash
        return False


# ---- JWT -------------------------------------------------------------------

def create_token(user: User) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_ALGORITHM)


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """Optional auth: returns the signed-in user, or ``None`` if the request is
    anonymous or the token is invalid/expired. Never raises — the app stays open."""
    token = _bearer(authorization)
    if not token:
        return None
    payload = _decode_token(token)
    if not payload:
        return None
    try:
        uid = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    return await session.get(User, uid)


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """Strict variant for endpoints that must have a signed-in user."""
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


# ---- Schemas ---------------------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    plan: str = "free"

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    token: str
    user: UserOut


# ---- Routes ----------------------------------------------------------------

@router.post("/signup", response_model=AuthResponse, status_code=201)
async def signup(
    payload: SignupRequest, session: AsyncSession = Depends(get_session)
) -> AuthResponse:
    email = payload.email.lower().strip()
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="an account with this email already exists")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        name=(payload.name or "").strip() or None,
        plan="free",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return AuthResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest, session: AsyncSession = Depends(get_session)
) -> AuthResponse:
    email = payload.email.lower().strip()
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    # Same error whether the email is unknown or the password is wrong — don't
    # leak which accounts exist.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    return AuthResponse(token=create_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(require_user)) -> User:
    return user
