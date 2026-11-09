"""Customer-care (CRM) contacts that admins manage and every party user sees prominently.

Supports multiple support-team contacts. Stored as a list in AppSetting under key 'crm_contacts'.
Migrates automatically from the legacy single-contact key 'crm_contact'.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import domain
from .auth import Principal, current_user, require_admin
from .db import SessionLocal, as_utc, utcnow
from .models import AppSetting, AuditLog

router = APIRouter(tags=["contact"])
KEY = "crm_contacts"
LEGACY_KEY = "crm_contact"
EMPTY_CONTACT = {"id": 0, "label": "Customer care", "phone": "", "alt_phone": "", "whatsapp": False, "email": "", "hours": ""}


def normalise_phone(raw: str) -> tuple[str, str]:
    """Return (display, tel-uri) for an Indian mobile or landline; raise ValueError if not a number."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return "", ""
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:   # landline with STD code, e.g. 0816 2xxxxxx
        return f"0{digits[1:5]} {digits[5:]}", f"+91{digits[1:]}"
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91 {digits[:5]} {digits[5:]}", f"+91{digits}"
    if len(digits) == 10:                                 # landline written without the leading 0
        return f"0{digits[:4]} {digits[4:]}", f"+91{digits}"
    if digits.startswith("1800") and len(digits) in (10, 11):    # toll-free, dialled without +91
        return f"{digits[:4]} {digits[4:7]} {digits[7:]}", digits
    raise ValueError("Enter a 10-digit mobile, a landline with STD code, or an 1800 number")


def public_view(v: dict) -> dict | None:
    v = {**EMPTY_CONTACT, **(v or {})}
    if not v["phone"]:
        return None
    disp, tel = normalise_phone(v["phone"])
    out = {"id": v.get("id", 0), "label": v["label"] or "Customer care", "phone": disp, "tel": tel,
           "whatsapp": f"https://wa.me/{tel.lstrip('+')}" if v["whatsapp"] and len(tel) == 13 else None,
           "email": v["email"] or None, "hours": v["hours"] or None, "alt_phone": None, "alt_tel": None}
    if v["alt_phone"]:
        out["alt_phone"], out["alt_tel"] = normalise_phone(v["alt_phone"])
    return out


def _next_id(contacts: list[dict]) -> int:
    return max((c.get("id", 0) for c in contacts), default=0) + 1


async def load_all() -> tuple[list[dict], AppSetting | None]:
    """Load all contacts. Auto-migrates from legacy single-contact format."""
    async with SessionLocal() as db:
        row = await db.get(AppSetting, KEY)
        if row:
            return (row.value or [], row)
        legacy = await db.get(AppSetting, LEGACY_KEY)
        if legacy and legacy.value and legacy.value.get("phone"):
            return ([{**EMPTY_CONTACT, **legacy.value, "id": 1}], legacy)
    return ([], None)


@router.get("/api/public/contact")
async def contact_public():
    """Unauthenticated: the sign-in page shows it for forgotten passwords."""
    contacts, _ = await load_all()
    items = [v for c in contacts if (v := public_view(c))]
    return {"contact": items[0] if items else None, "contacts": items}


@router.get("/api/contact")
async def contact(_: Principal = Depends(current_user)):
    contacts, _ = await load_all()
    items = [v for c in contacts if (v := public_view(c))]
    return {"contact": items[0] if items else None, "contacts": items}


class ContactIn(BaseModel):
    label: str = Field("Customer care", max_length=60)
    phone: str = Field("", max_length=32)
    alt_phone: str = Field("", max_length=32)
    whatsapp: bool = False
    email: str = Field("", max_length=120)
    hours: str = Field("", max_length=80)


def _validate_contact(v: dict) -> None:
    for field in ("phone", "alt_phone"):
        try:
            normalise_phone(v[field])
        except ValueError as e:
            raise HTTPException(422, f"{'Phone' if field == 'phone' else 'Alternate phone'}: {e}")
    if v["alt_phone"] and not v["phone"]:
        raise HTTPException(422, "Set the main phone number first")
    if v["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v["email"]):
        raise HTTPException(422, "Email address looks incomplete")
    if not v.get("phone"):
        raise HTTPException(422, "Phone number is required")


@router.get("/api/admin/contact")
async def contact_admin_get(_: Principal = Depends(require_admin)):
    contacts, row = await load_all()
    previews = [v for c in contacts if (v := public_view(c))]
    return {"contacts": contacts, "previews": previews,
            "updated_at": domain.iso_utc(as_utc(row.updated_at)) if row else None,
            "updated_by": row.updated_by if row else None}


@router.post("/api/admin/contact", status_code=201)
async def contact_admin_add(body: ContactIn, actor: Principal = Depends(require_admin)):
    v = {k: (val.strip() if isinstance(val, str) else val) for k, val in body.model_dump().items()}
    _validate_contact(v)
    async with SessionLocal() as db:
        row = await db.get(AppSetting, KEY)
        if not row:
            row = AppSetting(key=KEY, value=[])
            legacy = await db.get(AppSetting, LEGACY_KEY)
            if legacy and legacy.value and legacy.value.get("phone"):
                row.value = [{**EMPTY_CONTACT, **legacy.value, "id": 1}]
        contacts = list(row.value or [])
        v["id"] = _next_id(contacts)
        contacts.append(v)
        row.value, row.updated_at, row.updated_by = contacts, utcnow(), actor.username
        db.add(row)
        db.add(AuditLog(actor=actor.username, action="settings.contact", target=v["label"],
                        detail={"action": "added", **v}, at=utcnow()))
        await db.commit()
    previews = [pv for c in contacts if (pv := public_view(c))]
    return {"contacts": contacts, "previews": previews}


@router.put("/api/admin/contact/{contact_id}")
async def contact_admin_update(contact_id: int, body: ContactIn, actor: Principal = Depends(require_admin)):
    v = {k: (val.strip() if isinstance(val, str) else val) for k, val in body.model_dump().items()}
    _validate_contact(v)
    async with SessionLocal() as db:
        row = await db.get(AppSetting, KEY)
        if not row:
            raise HTTPException(404, "No contacts configured")
        contacts = list(row.value or [])
        idx = next((i for i, c in enumerate(contacts) if c.get("id") == contact_id), None)
        if idx is None:
            raise HTTPException(404, "Contact not found")
        before = contacts[idx]
        v["id"] = contact_id
        contacts[idx] = v
        row.value, row.updated_at, row.updated_by = contacts, utcnow(), actor.username
        db.add(row)
        changes = {k: val for k, val in v.items() if before.get(k) != val}
        db.add(AuditLog(actor=actor.username, action="settings.contact", target=v["label"],
                        detail={"action": "updated", **changes}, at=utcnow()))
        await db.commit()
    previews = [pv for c in contacts if (pv := public_view(c))]
    return {"contacts": contacts, "previews": previews}


@router.delete("/api/admin/contact/{contact_id}", status_code=200)
async def contact_admin_delete(contact_id: int, actor: Principal = Depends(require_admin)):
    async with SessionLocal() as db:
        row = await db.get(AppSetting, KEY)
        if not row:
            raise HTTPException(404, "No contacts configured")
        contacts = list(row.value or [])
        idx = next((i for i, c in enumerate(contacts) if c.get("id") == contact_id), None)
        if idx is None:
            raise HTTPException(404, "Contact not found")
        removed = contacts.pop(idx)
        row.value, row.updated_at, row.updated_by = contacts, utcnow(), actor.username
        db.add(row)
        db.add(AuditLog(actor=actor.username, action="settings.contact", target=removed.get("label", ""),
                        detail={"action": "deleted"}, at=utcnow()))
        await db.commit()
    previews = [pv for c in contacts if (pv := public_view(c))]
    return {"contacts": contacts, "previews": previews}


# ---- backwards-compatible single-contact PUT (kept for old clients) ----
@router.put("/api/admin/contact")
async def contact_admin_put_legacy(body: ContactIn, actor: Principal = Depends(require_admin)):
    """Legacy single-contact endpoint: upserts the first contact."""
    v = {k: (val.strip() if isinstance(val, str) else val) for k, val in body.model_dump().items()}
    _validate_contact(v)
    async with SessionLocal() as db:
        row = await db.get(AppSetting, KEY) or AppSetting(key=KEY, value=[])
        contacts = list(row.value or [])
        if contacts:
            v["id"] = contacts[0].get("id", 1)
            contacts[0] = v
        else:
            v["id"] = 1
            contacts.append(v)
        row.value, row.updated_at, row.updated_by = contacts, utcnow(), actor.username
        db.add(row)
        db.add(AuditLog(actor=actor.username, action="settings.contact", target=v["label"],
                        detail={"action": "updated", **v}, at=utcnow()))
        await db.commit()
    previews = [pv for c in contacts if (pv := public_view(c))]
    return {"contacts": contacts, "previews": previews, "contact": v, "preview": public_view(v)}
