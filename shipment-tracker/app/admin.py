"""User master for Balaji Transports staff: create logins and assign the party names each can track."""
from __future__ import annotations

import re
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, delete, func, select

from . import domain
from .auth import Principal, hash_password, require_admin
from .db import SessionLocal, as_utc, utcnow
from .models import AuditLog, Notification, Shipment, User, UserPartyName

router = APIRouter(prefix="/api/admin", tags=["admin"])
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def generate_password() -> str:
    return secrets.token_urlsafe(12)


def _user_out(u: User) -> dict:
    return {
        "id": u.id, "username": u.username, "display_name": u.display_name, "company": u.company,
        "email": u.email, "phone": u.phone, "role": u.role, "active": u.active,
        "party_names": [p.party_name for p in u.party_names],
        "must_change_password": u.must_change_password,
        "whatsapp_alerts": u.whatsapp_alerts,
        "last_login_at": domain.iso_utc(as_utc(u.last_login_at)),
        "created_at": domain.iso_utc(as_utc(u.created_at)),
    }


def _clean_names(names: list[str]) -> list[tuple[str, str]]:
    out: dict[str, str] = {}
    for n in names:
        n = re.sub(r"\s+", " ", (n or "").strip())
        key = domain.norm_party(n)
        if key and key not in out:
            out[key] = n
    return [(name, key) for key, name in out.items()]


async def _audit(db, actor: Principal, action: str, target: str, detail: dict | None = None) -> None:
    db.add(AuditLog(actor=actor.username, action=action, target=target, detail=detail or {}, at=utcnow()))


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    display_name: str = Field("", max_length=128)
    company: str = Field("", max_length=255)
    email: str = Field("", max_length=255)
    phone: str = Field("", max_length=32)
    role: Literal["party", "admin"] = "party"
    password: Optional[str] = Field(None, max_length=256)
    whatsapp_alerts: bool = True
    party_names: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().casefold()
        if not USERNAME_RE.match(v):
            raise ValueError("3-64 characters: letters, digits, dot, dash or underscore")
        return v


class UserPatch(BaseModel):
    display_name: Optional[str] = Field(None, max_length=128)
    company: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=32)
    role: Optional[Literal["party", "admin"]] = None
    active: Optional[bool] = None
    whatsapp_alerts: Optional[bool] = None
    party_names: Optional[list[str]] = Field(None, max_length=200)


@router.get("/users")
async def list_users(q: str = Query("", max_length=64),
                     limit: int = Query(50, ge=1, le=200),
                     offset: int = Query(0, ge=0),
                     _: Principal = Depends(require_admin)):
    stmt = select(User).order_by(User.role.desc(), User.company, User.username)
    if q.strip():
        like = f"%{q.strip()}%"
        sub = select(UserPartyName.user_id).where(UserPartyName.party_name.ilike(like))
        stmt = stmt.where((User.username.ilike(like)) | (User.company.ilike(like)) |
                          (User.display_name.ilike(like)) | (User.id.in_(sub)))
    async with SessionLocal() as db:
        rows = (await db.scalars(stmt.offset(offset).limit(limit + 1))).all()
    has_more = len(rows) > limit
    return {"items": [_user_out(u) for u in rows[:limit]], "has_more": has_more}


@router.post("/users", status_code=201)
async def create_user(body: UserIn, actor: Principal = Depends(require_admin)):
    password = body.password or generate_password()
    try:
        pw_hash = hash_password(password)
    except ValueError as e:
        raise HTTPException(422, str(e))
    now = utcnow()
    async with SessionLocal() as db:
        if await db.scalar(select(User.id).where(User.username == body.username)):
            raise HTTPException(409, f"Username '{body.username}' is already taken")
        user = User(username=body.username, display_name=body.display_name.strip(), company=body.company.strip(),
                    email=body.email.strip(), phone=body.phone.strip(), role=body.role, password_hash=pw_hash,
                    must_change_password=True, whatsapp_alerts=body.whatsapp_alerts, created_at=now, updated_at=now)
        user.party_names = [UserPartyName(party_name=n, party_key=k) for n, k in _clean_names(body.party_names)]
        db.add(user)
        await db.flush()
        await _audit(db, actor, "user.create", user.username, {"role": user.role, "party_names": body.party_names})
        await db.commit()
        await db.refresh(user)
    return {"user": _user_out(user), "password": password if not body.password else None}


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserPatch, actor: Principal = Depends(require_admin)):
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        if user.id == actor.user_id and (body.active is False or body.role == "party"):
            raise HTTPException(409, "You cannot disable or demote your own account")
        changes: dict = {}
        for field in ("display_name", "company", "email", "phone"):
            v = getattr(body, field)
            if v is not None and v.strip() != getattr(user, field):
                changes[field] = v.strip()
                setattr(user, field, v.strip())
        if body.role is not None and body.role != user.role:
            changes["role"] = body.role
            user.role = body.role
            user.token_version += 1
        if body.active is not None and body.active != user.active:
            changes["active"] = body.active
            user.active = body.active
            user.token_version += 1
        if body.whatsapp_alerts is not None and body.whatsapp_alerts != user.whatsapp_alerts:
            changes["whatsapp_alerts"] = body.whatsapp_alerts
            user.whatsapp_alerts = body.whatsapp_alerts
        if body.party_names is not None:
            wanted = _clean_names(body.party_names)
            current = {p.party_key: p for p in user.party_names}
            wanted_keys = {k for _, k in wanted}
            removed = [p.party_name for k, p in current.items() if k not in wanted_keys]
            added = [n for n, k in wanted if k not in current]
            user.party_names = [p for k, p in current.items() if k in wanted_keys] + \
                [UserPartyName(party_name=n, party_key=k) for n, k in wanted if k not in current]
            if removed or added:
                changes["party_names"] = {"added": added, "removed": removed}
                if removed:  # drop alerts about shipments this user can no longer see
                    gone = select(Shipment.id).where(Shipment.party_key.in_([domain.norm_party(n) for n in removed]))
                    await db.execute(delete(Notification).where(Notification.user_id == user.id,
                                                                Notification.shipment_id.in_(gone)))
        if changes:
            user.updated_at = utcnow()
            await _audit(db, actor, "user.update", user.username, changes)
        await db.commit()
        await db.refresh(user)
    return {"user": _user_out(user)}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, actor: Principal = Depends(require_admin)):
    password = generate_password()
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        user.password_hash = hash_password(password)
        user.token_version += 1
        user.must_change_password = True  # the admin knows this one; the user must replace it
        user.updated_at = utcnow()
        await _audit(db, actor, "user.reset_password", user.username)
        await db.commit()
    return {"password": password}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, actor: Principal = Depends(require_admin)):
    if user_id == actor.user_id:
        raise HTTPException(409, "You cannot delete your own account")
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(404, "User not found")
        await _audit(db, actor, "user.delete", user.username)
        await db.delete(user)
        await db.commit()


@router.get("/party-names")
async def party_names(q: str = Query("", max_length=100), _: Principal = Depends(require_admin)):
    """Every PartyName seen upstream, with shipment counts and which users track it."""
    stmt = (select(Shipment.party_key, func.max(Shipment.party_name_raw), func.count(),
                   func.sum(case((Shipment.status != "delivered", 1), else_=0)), func.max(Shipment.shipment_date))
            .where(Shipment.party_key != "").group_by(Shipment.party_key))
    async with SessionLocal() as db:
        rows = (await db.execute(stmt)).all()
        assigned: dict[str, list[str]] = {}
        for key, uname in (await db.execute(
            select(UserPartyName.party_key, User.username).join(User, User.id == UserPartyName.user_id)
        )).all():
            assigned.setdefault(key, []).append(uname)
    term = domain.norm_party(q)
    items = [
        {"party_name": name, "shipments": n, "active": int(act or 0), "last_shipment": last,
         "users": sorted(assigned.get(key, []))}
        for key, name, n, act, last in rows if not term or term in key
    ]
    items.sort(key=lambda x: (-x["active"], -x["shipments"], x["party_name"]))
    return {"items": items}


@router.get("/audit")
async def audit(limit: int = Query(50, ge=1, le=500), before: int = Query(0, ge=0), _: Principal = Depends(require_admin)):
    async with SessionLocal() as db:
        stmt = select(AuditLog).order_by(AuditLog.id.desc())
        if before:
            stmt = stmt.where(AuditLog.id < before)
        rows = (await db.scalars(stmt.limit(limit + 1))).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    return {"items": [{"id": r.id, "actor": r.actor, "action": r.action, "target": r.target, "detail": r.detail,
                       "at": domain.iso_utc(as_utc(r.at))} for r in items],
            "has_more": has_more}
