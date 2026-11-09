from __future__ import annotations

import time
from datetime import timedelta

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from .config import get_settings
from .db import SessionLocal, utcnow
from .models import AuditLog, LoginAttempt, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
_ALG = "HS256"
_DUMMY_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt(rounds=12)).decode()


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


# ------------------------------------------------------------------ throttling (DB-backed)
async def _throttle_blocked(key: str) -> bool:
    s = get_settings()
    cutoff = utcnow() - timedelta(seconds=s.login_window_seconds)
    async with SessionLocal() as db:
        count = await db.scalar(
            select(func.count()).select_from(LoginAttempt)
            .where(LoginAttempt.key == key, LoginAttempt.at >= cutoff))
    return (count or 0) >= s.login_max_attempts


async def _throttle_fail(key: str) -> None:
    async with SessionLocal() as db:
        db.add(LoginAttempt(key=key, at=utcnow()))
        await db.commit()


async def _throttle_reset(key: str) -> None:
    async with SessionLocal() as db:
        await db.execute(delete(LoginAttempt).where(LoginAttempt.key == key))
        await db.commit()


# ------------------------------------------------------------------ sessions
def issue_session(user: User) -> tuple[str, int]:
    s = get_settings()
    ttl = int(timedelta(hours=s.session_ttl_hours).total_seconds())
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(user.id), "ver": user.token_version, "role": user.role, "iat": now, "exp": now + ttl},
        s.session_secret, algorithm=_ALG,
    )
    return token, ttl


class Principal(BaseModel):
    user_id: int
    username: str
    display_name: str
    company: str
    role: str
    party_keys: list[str]
    exp: int

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


async def current_user(request: Request) -> Principal:
    s = get_settings()
    token = request.cookies.get(s.cookie_name)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")
    try:
        claims = jwt.decode(token, s.session_secret, algorithms=[_ALG], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Sign in again.")
    async with SessionLocal() as db:
        user = await db.get(User, int(claims["sub"]))
    # token_version changes on password reset, role change or disable -> old cookies stop working
    if not user or not user.active or user.token_version != claims.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has ended. Sign in again.")
    return Principal(user_id=user.id, username=user.username, display_name=user.display_name or user.username,
                     company=user.company or "", role=user.role,
                     party_keys=[p.party_key for p in user.party_names], exp=int(claims["exp"]))


async def require_admin(p: Principal = Depends(current_user)) -> Principal:
    if not p.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access required")
    return p


# ------------------------------------------------------------------ routes
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For only via uvicorn --proxy-headers behind your own proxy.
    return request.client.host if request.client else "unknown"


def _me(p_user: User | Principal) -> dict:
    return {"username": p_user.username, "display_name": p_user.display_name or p_user.username,
            "company": p_user.company or "", "role": p_user.role}


def _set_session_cookie(response: Response, user: User) -> None:
    s = get_settings()
    token, ttl = issue_session(user)
    response.set_cookie(s.cookie_name, token, max_age=ttl, httponly=True, secure=s.cookie_secure,
                        samesite="strict", path="/")


def password_problem(password: str, username: str) -> str | None:
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(password) > 128:
        return "Use at most 128 characters."
    if username and username.casefold() in password.casefold():
        return "The password must not contain your username."
    if len(set(password)) < 5:
        return "Choose a less repetitive password."
    return None


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    s = get_settings()
    username = body.username.strip().casefold()
    key = f"{_client_ip(request)}|{username}"
    if await _throttle_blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait 15 minutes and try again.")

    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == username))
        ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
        if not user or not ok or not user.active:
            await _throttle_fail(key)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username or password is incorrect.")
        user.last_login_at = utcnow()
        await db.commit()

    await _throttle_reset(key)
    _set_session_cookie(response, user)
    return {"user": _me(user), "must_change_password": user.must_change_password}


@router.post("/logout", status_code=204)
async def logout(response: Response):
    s = get_settings()
    response.delete_cookie(s.cookie_name, path="/", secure=s.cookie_secure, httponly=True, samesite="strict")


@router.get("/me")
async def me(p: Principal = Depends(current_user)):
    async with SessionLocal() as db:
        user = await db.get(User, p.user_id)
        names = [n.party_name for n in user.party_names] if user and not p.is_admin else []
    return {"user": _me(p), "party_names": names, "session_expires_at": p.exp,
            "must_change_password": bool(user and user.must_change_password)}


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, request: Request, response: Response,
                          p: Principal = Depends(current_user)):
    key = f"pw|{p.user_id}"
    if await _throttle_blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait 15 minutes and try again.")
    async with SessionLocal() as db:
        user = await db.get(User, p.user_id)
        if not user or not verify_password(body.current_password, user.password_hash):
            await _throttle_fail(key)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect.")
        if body.new_password == body.current_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The new password must be different from the current one.")
        if problem := password_problem(body.new_password, user.username):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
        user.password_hash = hash_password(body.new_password)
        user.token_version += 1          # signs out every other session
        user.must_change_password = False
        user.password_changed_at = utcnow()
        db.add(AuditLog(actor=user.username, action="user.change_password", target=user.username, detail={}, at=utcnow()))
        await db.commit()
        await db.refresh(user)
    await _throttle_reset(key)
    _set_session_cookie(response, user)  # keep this browser signed in with the new token version
    return {"ok": True}
