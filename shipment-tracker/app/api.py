"""Party-facing API. Every query is scoped by the signed-in user's party names
(admins see everything)."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import timedelta
from typing import Literal, Optional

from datetime import date, datetime, time as dtime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select, update

from . import domain
from .auth import Principal, current_user
from .config import get_settings
from .db import SessionLocal, as_utc, utcnow
from .models import Notification, Shipment, TrackPoint, VehiclePosition

router = APIRouter(prefix="/api", tags=["tracking"])

_sse_conns: dict[int, int] = {}
_SSE_MAX_PER_USER = 3


def visible(p: Principal):
    """Row filter for what this user may see: admins see all, parties see their party names."""
    if p.is_admin:
        return Shipment.id.is_not(None)
    return Shipment.party_key.in_(p.party_keys or ["__none__"])


def _trackable(sh: Shipment) -> bool:
    return sh.status != "delivered" and sh.superseded_by is None


def serialize(sh: Shipment, pos: VehiclePosition | None, detail: bool = False, staff: bool = False) -> dict:
    s = get_settings()
    live = _trackable(sh)
    out = {
        "id": sh.id,
        "party_name": sh.party_name_raw,
        "vehicle_no": sh.vehicle_no,
        "product": sh.product,
        "net_weight": sh.net_weight,
        "shipment_date": sh.shipment_date,
        "origin": sh.origin or "Toranagallu",
        "destination": sh.destination,
        "unload_site": sh.unload_site,
        "status": sh.status,
        "status_label": domain.STATUS_LABEL[sh.status],
        "status_text": domain.status_sentence(sh.status, sh.destination, sh.unload_site, sh.delivered_inferred),
        "status_at": domain.iso_utc(as_utc(sh.status_at)),
        "delivered_inferred": sh.delivered_inferred,
        "tracking": live,
        "driver": None,
        "position": None,
    }
    if live:
        if staff:  # driver contact is internal: Balaji Transports staff only; parties go through customer care
            out["driver"] = {"phones": [p for p in sh.driver_phones.split(",") if p]}
        if pos is not None:
            fix = as_utc(pos.fix_at)
            out["position"] = {
                "lat": pos.lat, "lng": pos.lng, "heading": pos.heading, "at": domain.iso_utc(fix),
                "stale": (utcnow() - fix) > timedelta(minutes=s.gps_stale_minutes),
            }
    if detail:
        out["timeline"] = domain.build_timeline(sh.milestones or {}, sh.destination, sh.status,
                                                sh.delivered_inferred, as_utc(sh.status_at))
    return out


@router.get("/config")
async def config(_: Principal = Depends(current_user)):
    s = get_settings()
    base = "/olamaps/tiles/vector/v1/styles/{}/style.json"
    return {
        "map": {
            "ready": bool(s.ola_maps_api_key),
            "style_light": base.format(s.ola_style_light),
            "style_dark": base.format(s.ola_style_dark),
            "attribution": "&copy; Ola Maps &copy; OpenStreetMap contributors",
        },
        "refresh_seconds": max(20, s.location_poll_seconds // 2),
        "gps_stale_minutes": s.gps_stale_minutes,
    }


STATUS_GROUPS = {
    "loading": ["assigned", "loading"],
    "transit": ["dispatched", "in_transit", "near_destination"],
    "site": ["arrived"],
}


@router.get("/shipments")
async def list_shipments(
    scope: Literal["active", "delivered", "all"] = "active",
    q: str = Query("", max_length=64),
    party: str = Query("", max_length=255),
    status_group: str = Query("", max_length=20),
    since: str = Query("", max_length=10),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    p: Principal = Depends(current_user),
):
    s = get_settings()
    rank = case({k: v for k, v in domain.RANK.items()}, value=Shipment.status, else_=0)
    base = [visible(p)]
    if party.strip():
        base.append(Shipment.party_key == domain.norm_party(party))
    stmt = (
        select(Shipment, VehiclePosition)
        .outerjoin(VehiclePosition, VehiclePosition.vehicle_id == Shipment.vehicle_id)
        .where(*base)
    )
    if since.strip():
        try:
            cutoff = datetime.combine(date.fromisoformat(since.strip()), dtime(0), tzinfo=domain.IST).astimezone(domain.UTC)
        except ValueError:
            cutoff = utcnow() - timedelta(days=s.delivered_visible_days)
    else:
        cutoff = utcnow() - timedelta(days=s.delivered_visible_days)
    today_start = datetime.combine(datetime.now(domain.IST).date(), dtime(0), tzinfo=domain.IST).astimezone(domain.UTC)
    not_superseded = Shipment.superseded_by.is_(None)
    if status_group == "done_today":
        stmt = stmt.where(Shipment.status == "delivered", Shipment.status_at >= today_start).order_by(Shipment.status_at.desc())
    elif status_group in STATUS_GROUPS:
        stmt = stmt.where(Shipment.status.in_(STATUS_GROUPS[status_group]), not_superseded).order_by(rank.desc(), Shipment.status_at.desc())
    elif scope == "active":
        stmt = stmt.where(Shipment.status != "delivered", not_superseded).order_by(rank.desc(), Shipment.status_at.desc())
    elif scope == "delivered":
        stmt = stmt.where(Shipment.status == "delivered", Shipment.status_at >= cutoff).order_by(Shipment.status_at.desc())
    else:
        stmt = stmt.where(or_(Shipment.status != "delivered", Shipment.status_at >= cutoff)).order_by(Shipment.status_at.desc())
    term = q.strip()
    if term:
        like = f"%{term.replace(' ', '')}%"
        conds = [
            func.replace(Shipment.vehicle_no, " ", "").ilike(like),
            Shipment.product.ilike(f"%{term}%"),
            Shipment.unload_site.ilike(f"%{term}%"),
            Shipment.destination.ilike(f"%{term}%"),
            Shipment.party_name_raw.ilike(f"%{term}%"),
        ]
        if term.isdigit():
            conds.append(Shipment.id == int(term))
        stmt = stmt.where(or_(*conds))
    rows = (await _exec(stmt.offset(offset).limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    # KPI strip: counts by status for the same visibility (ignoring search text)
    today_ist = datetime.combine(datetime.now(domain.IST).date(), dtime(0), tzinfo=domain.IST)
    async with SessionLocal() as db:
        by_status = dict((await db.execute(
            select(Shipment.status, func.count()).where(*base, Shipment.status != "delivered", Shipment.superseded_by.is_(None)).group_by(Shipment.status)
        )).all())
        delivered_recent = await db.scalar(
            select(func.count()).select_from(Shipment).where(*base, Shipment.status == "delivered", Shipment.status_at >= cutoff))
        delivered_today = await db.scalar(
            select(func.count()).select_from(Shipment).where(*base, Shipment.status == "delivered",
                                                             Shipment.status_at >= today_ist.astimezone(domain.UTC)))
    active = sum(by_status.values())
    return {
        "items": [serialize(sh, pos, staff=p.is_admin) for sh, pos in rows],
        "has_more": has_more,
        "counts": {"active": active, "delivered": delivered_recent or 0},
        "summary": {
            "loading": by_status.get("assigned", 0) + by_status.get("loading", 0),
            "in_transit": by_status.get("dispatched", 0) + by_status.get("in_transit", 0) + by_status.get("near_destination", 0),
            "at_site": by_status.get("arrived", 0),
            "delivered_today": delivered_today or 0,
        },
        "server_time": domain.iso_utc(utcnow()),
    }


async def _exec(stmt):
    async with SessionLocal() as db:
        return await db.execute(stmt)


@router.get("/shipments/export.csv")
async def export_csv(
    scope: Literal["active", "delivered", "all"] = "active",
    party: str = Query("", max_length=255),
    since: str = Query("", max_length=10),
    p: Principal = Depends(current_user),
):
    import csv, io
    s = get_settings()
    base = [visible(p)]
    if party.strip():
        base.append(Shipment.party_key == domain.norm_party(party))
    stmt = select(Shipment).where(*base)
    if since.strip():
        try:
            cutoff = datetime.combine(date.fromisoformat(since.strip()), dtime(0), tzinfo=domain.IST).astimezone(domain.UTC)
        except ValueError:
            cutoff = utcnow() - timedelta(days=s.delivered_visible_days)
    else:
        cutoff = utcnow() - timedelta(days=s.delivered_visible_days)
    if scope == "active":
        stmt = stmt.where(Shipment.status != "delivered", Shipment.superseded_by.is_(None))
    elif scope == "delivered":
        stmt = stmt.where(Shipment.status == "delivered", Shipment.status_at >= cutoff)
    else:
        stmt = stmt.where(or_(Shipment.status != "delivered", Shipment.status_at >= cutoff))
    stmt = stmt.order_by(Shipment.status_at.desc()).limit(2000)
    async with SessionLocal() as db:
        rows = (await db.scalars(stmt)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "Vehicle No", "Party", "Product", "Weight (t)", "Origin", "Destination", "Site", "Status", "Date", "Delivered At"])
    for sh in rows:
        w.writerow([
            sh.id, sh.vehicle_no, sh.party_name_raw, sh.product,
            sh.net_weight, sh.origin, sh.destination, sh.unload_site,
            domain.STATUS_LABEL[sh.status], sh.shipment_date,
            domain.iso_utc(as_utc(sh.status_at)) if sh.status == "delivered" else "",
        ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=shipments_{scope}.csv"},
    )


@router.get("/shipments/{shipment_id}")
async def get_shipment(shipment_id: int, p: Principal = Depends(current_user)):
    async with SessionLocal() as db:
        row = (await db.execute(
            select(Shipment, VehiclePosition)
            .outerjoin(VehiclePosition, VehiclePosition.vehicle_id == Shipment.vehicle_id)
            .where(Shipment.id == shipment_id, visible(p))
        )).first()
        if not row:
            raise HTTPException(404, "Shipment not found")
        sh, pos = row
        data = serialize(sh, pos, detail=True, staff=p.is_admin)
        data["trail"] = []
        if _trackable(sh):
            pts = (await db.execute(
                select(TrackPoint.lat, TrackPoint.lng).where(TrackPoint.shipment_id == sh.id)
                .order_by(TrackPoint.at).limit(2000)
            )).all()
            data["trail"] = [[a, b] for a, b in pts]
    return data


# ------------------------------------------------------------------ notifications
def _notif(n: Notification) -> dict:
    return {"id": n.id, "shipment_id": n.shipment_id, "kind": n.kind, "title": n.title, "body": n.body,
            "created_at": domain.iso_utc(as_utc(n.created_at)), "read": n.read_at is not None}


@router.get("/notifications")
async def list_notifications(limit: int = Query(50, ge=1, le=200), p: Principal = Depends(current_user)):
    async with SessionLocal() as db:
        items = (await db.scalars(
            select(Notification).where(Notification.user_id == p.user_id).order_by(Notification.id.desc()).limit(limit)
        )).all()
        unread = await db.scalar(
            select(func.count()).select_from(Notification)
            .where(Notification.user_id == p.user_id, Notification.read_at.is_(None))
        )
    return {"items": [_notif(n) for n in items], "unread": unread or 0}


class MarkRead(BaseModel):
    ids: Optional[list[int]] = None


@router.post("/notifications/read")
async def mark_read(body: MarkRead, p: Principal = Depends(current_user)):
    stmt = update(Notification).where(Notification.user_id == p.user_id, Notification.read_at.is_(None))
    if body.ids:
        stmt = stmt.where(Notification.id.in_(body.ids[:500]))
    async with SessionLocal() as db:
        await db.execute(stmt.values(read_at=utcnow()))
        await db.commit()
    return {"ok": True}


@router.get("/events")
async def events(request: Request, p: Principal = Depends(current_user)):
    """Server-sent events. Reads from the DB, so it works with any number of web workers."""
    if _sse_conns.get(p.user_id, 0) >= _SSE_MAX_PER_USER:
        raise HTTPException(429, "Too many open event streams")
    last_event = request.headers.get("last-event-id", "")

    async def stream():
        _sse_conns[p.user_id] = _sse_conns.get(p.user_id, 0) + 1
        try:
            async with SessionLocal() as db:
                cursor = int(last_event) if last_event.isdigit() else (
                    await db.scalar(select(func.max(Notification.id)).where(Notification.user_id == p.user_id)) or 0
                )
            yield "retry: 5000\n\n"
            ticks = 0
            while not await request.is_disconnected():
                if time.time() >= p.exp:
                    yield "event: session-expired\ndata: {}\n\n"
                    return
                async with SessionLocal() as db:
                    fresh = (await db.scalars(
                        select(Notification).where(Notification.user_id == p.user_id, Notification.id > cursor)
                        .order_by(Notification.id).limit(50)
                    )).all()
                for n in fresh:
                    cursor = n.id
                    yield f"id: {n.id}\nevent: notification\ndata: {json.dumps(_notif(n))}\n\n"
                ticks += 1
                if ticks % 3 == 0:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(5)
        finally:
            _sse_conns[p.user_id] = max(0, _sse_conns.get(p.user_id, 1) - 1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
