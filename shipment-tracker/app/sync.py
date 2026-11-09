"""Background poller: pulls upstream shipments and GPS, derives status, raises notifications.

Run exactly one poller per deployment (RUN_POLLER=true on one process only).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from . import domain
from .config import get_settings
from .db import SessionLocal, as_utc, utcnow
from .models import LoginAttempt, Notification, Shipment, SyncState, TrackPoint, User, UserPartyName, VehiclePosition
from .upstream import UpstreamClient

log = logging.getLogger("tracker.sync")


def _float(v: Any) -> float | None:
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class Syncer:
    def __init__(self, client: UpstreamClient) -> None:
        self.client = client
        self.s = get_settings()
        self._stop = asyncio.Event()
        self._last_point: dict[int, tuple[float, float, datetime]] = {}
        self._last_purge: datetime | None = None
        self._pending_wa: list[tuple[list[str], str]] = []

    # ------------------------------------------------------------ loop plumbing
    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        tasks = [
            self._loop("shipments", self.sync_shipments, self.s.shipment_poll_seconds),
            self._loop("locations", self.sync_locations, self.s.location_poll_seconds, initial_delay=5),
        ]
        if self.s.backup_enabled and self.s.database_url.startswith("sqlite"):
            tasks.append(self._loop("backup", self._backup_db, self.s.backup_interval_hours * 3600, initial_delay=60))
        await asyncio.gather(*tasks)

    async def _loop(self, key: str, fn, interval: int, initial_delay: int = 0) -> None:
        if initial_delay:
            await asyncio.sleep(initial_delay)
        while not self._stop.is_set():
            try:
                await fn()
                await self._mark(key, None)
            except Exception as e:  # noqa: BLE001 - keep polling whatever happens
                log.exception("%s sync failed", key)
                await self._mark(key, str(e)[:500])
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _mark(self, key: str, error: str | None) -> None:
        try:
            async with SessionLocal() as s:
                row = await s.get(SyncState, key) or SyncState(key=key, error="")
                if error is None:
                    row.ok_at, row.error = utcnow(), ""
                else:
                    row.error_at, row.error = utcnow(), error
                s.add(row)
                await s.commit()
        except Exception:  # noqa: BLE001
            log.exception("could not record sync state")

    # ------------------------------------------------------------ backup
    async def _backup_db(self) -> None:
        db_path = Path(self.s.database_url.split("///", 1)[-1])
        if not db_path.exists():
            return
        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"tracker_{stamp}.db"
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
            log.info("database backup created: %s", dest.name)
        finally:
            dst.close()
            src.close()
        backups = sorted(backup_dir.glob("tracker_*.db"))
        for old in backups[:-self.s.backup_keep]:
            old.unlink(missing_ok=True)
            log.info("old backup removed: %s", old.name)

    # ------------------------------------------------------------ shipments
    async def sync_shipments(self) -> None:
        today = datetime.now(domain.IST).date()
        rows = await self.client.fetch_shipments(today - timedelta(days=self.s.lookback_days), today)
        await self.ingest(rows)
        await self._refresh_stragglers(today)

    async def _refresh_stragglers(self, today: date) -> None:
        """Active shipments older than the lookback window still need updates; fetch them per vehicle."""
        cutoff = (today - timedelta(days=self.s.lookback_days)).isoformat()
        async with SessionLocal() as s:
            rows = (await s.execute(
                select(Shipment.vehicle_id, func.min(Shipment.shipment_date))
                .where(Shipment.status != "delivered", Shipment.shipment_date < cutoff)
                .group_by(Shipment.vehicle_id)
                .limit(self.s.straggler_limit)
            )).all()
        for vehicle_id, oldest in rows:
            start = date.fromisoformat(oldest) - timedelta(days=1)
            try:
                await self.ingest(await self.client.fetch_shipments(start, today, vehicle_id=vehicle_id))
            except Exception:  # noqa: BLE001
                log.exception("straggler refresh failed for vehicle %s", vehicle_id)

    async def ingest(self, rows: list[dict[str, Any]]) -> None:
        now = utcnow()
        rows = [r for r in rows if _int(r.get("ShipmentID")) is not None]
        self._pending_wa.clear()
        async with SessionLocal() as s:
            key_users: dict[str, list[int]] = defaultdict(list)
            key_wa_phones: dict[str, list[str]] = defaultdict(list)
            for key, uid, phone, wa_on in (await s.execute(
                select(UserPartyName.party_key, User.id, User.phone, User.whatsapp_alerts)
                .join(User, User.id == UserPartyName.user_id)
                .where(User.active.is_(True), User.role == "party")
            )).all():
                key_users[key].append(uid)
                if wa_on and phone:
                    for p in domain.clean_phones(phone):
                        wa_num = f"91{p}"
                        if wa_num not in key_wa_phones[key]:
                            key_wa_phones[key].append(wa_num)
            bootstrap = (await s.scalar(select(func.count(Shipment.id)))) == 0

            ids = [int(r["ShipmentID"]) for r in rows]
            existing: dict[int, Shipment] = {}
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                for sh in (await s.scalars(select(Shipment).where(Shipment.id.in_(chunk)))).all():
                    existing[sh.id] = sh

            for raw in rows:
                sid = int(raw["ShipmentID"])
                status, status_at, inferred = domain.derive_status(raw)
                values = dict(
                    party_key=domain.norm_party(raw.get("PartyName")),
                    party_name_raw=str(raw.get("PartyName") or "").strip(),
                    vehicle_id=_int(raw.get("VehicleID")) or 0,
                    vehicle_no=domain.format_plate(raw.get("VehicleNo")),
                    driver_name=domain.clean_driver_name(raw.get("Driver")),
                    driver_phones=",".join(domain.clean_phones(raw.get("MobileNo"))),
                    product=str(raw.get("ProductName") or "").strip(),
                    net_weight=_float(raw.get("NtWt")),
                    shipment_date=str(raw.get("ShipmentDate") or "")[:10],
                    origin=str(raw.get("From") or "").strip().title(),
                    destination=str(raw.get("TO") or "").strip(),
                    destination_id=_int(raw.get("DestinationID")),
                    unload_site=str(raw.get("Unload") or "").strip().rstrip("."),
                    milestones={k: raw.get(k) for k in domain.MILESTONE_FIELDS + domain.RETURN_FIELDS},
                )
                sh = existing.get(sid)
                if sh is None:
                    sh = Shipment(id=sid, status=status, status_at=status_at, delivered_inferred=inferred,
                                  first_seen_at=now, updated_at=now, **values)
                    s.add(sh)
                    existing[sid] = sh
                    ship_age = (now - (status_at or now)).total_seconds() if status_at else 0
                    if not bootstrap and status != "delivered" and ship_age < 3 * 86400:
                        self._notify(s, sh, status, key_users, key_wa_phones, new=(domain.RANK[status] <= domain.RANK["loading"]))
                    continue

                changed = any(getattr(sh, k) != v for k, v in values.items())
                for k, v in values.items():
                    setattr(sh, k, v)
                if sh.delivered_inferred and status != "delivered":
                    sh.status, sh.status_at, sh.delivered_inferred = status, status_at, False
                    changed = True
                elif domain.RANK[status] > domain.RANK[sh.status]:
                    sh.status, sh.status_at, sh.delivered_inferred = status, status_at, inferred
                    changed = True
                    if not bootstrap:
                        self._notify(s, sh, status, key_users, key_wa_phones)
                elif status == "delivered" and sh.delivered_inferred and not inferred:
                    sh.status_at, sh.delivered_inferred, sh.superseded_by = status_at, False, None
                    changed = True
                if changed:
                    sh.updated_at = now

            await s.flush()
            await self._close_superseded(s, bootstrap, key_users, key_wa_phones)
            await s.commit()

        if self._pending_wa and self.s.whatsapp_enabled:
            for phones, msg in self._pending_wa:
                await self.client.send_whatsapp(phones, msg)
            self._pending_wa.clear()

    async def _close_superseded(self, s, bootstrap: bool, key_users: dict[str, list[int]],
                                    key_wa_phones: dict[str, list[str]]) -> None:
        """Mark older open shipments for a vehicle so the GPS pin follows the newest load only.
        Does NOT change status to delivered — only the upstream unloadedTime does that."""
        open_rows = (await s.scalars(select(Shipment).where(Shipment.status != "delivered"))).all()
        by_vehicle: dict[int, list[Shipment]] = defaultdict(list)
        for sh in open_rows:
            by_vehicle[sh.vehicle_id].append(sh)
        now = utcnow()
        for lst in by_vehicle.values():
            if len(lst) < 2:
                continue
            lst.sort(key=lambda x: x.id)
            newest = lst[-1]
            for old in lst[:-1]:
                if old.superseded_by != newest.id:
                    old.superseded_by, old.updated_at = newest.id, now

    def _notify(self, s, sh: Shipment, status: str, key_users: dict[str, list[int]],
                key_wa_phones: dict[str, list[str]], new: bool = False) -> None:
        """Fan out one notification per party user who tracks this PartyName."""
        users = key_users.get(sh.party_key) or []
        if not users:
            return
        title, body = domain.notification_text(
            status, sh.vehicle_no, sh.product, sh.destination, sh.unload_site,
            inferred=sh.delivered_inferred, new=new,
        )
        now = utcnow()
        for uid in users:
            s.add(Notification(user_id=uid, shipment_id=sh.id, kind="new" if new else status,
                               title=title, body=body, created_at=now))
        phones = key_wa_phones.get(sh.party_key) or []
        if phones:
            self._pending_wa.append((list(phones), f"*{title}*\n{body}"))

    # ------------------------------------------------------------ GPS
    async def sync_locations(self) -> None:
        rows = await self.client.fetch_locations()
        positions: dict[int, dict[str, Any]] = {}
        for r in rows:
            vid = _int(r.get("Vehicleid"))
            pos = domain.parse_position(r) if vid else None
            if vid and pos:
                positions[vid] = pos

        now = utcnow()
        async with SessionLocal() as s:
            active = (await s.execute(
                select(Shipment.id, Shipment.vehicle_id, Shipment.status).where(Shipment.status != "delivered")
            )).all()
            vids = {vid for _, vid, _ in active if vid in positions}
            stored = {
                p.vehicle_id: p
                for p in (await s.scalars(select(VehiclePosition).where(VehiclePosition.vehicle_id.in_(vids)))).all()
            } if vids else {}
            for vid in vids:
                pos = positions[vid]
                row = stored.get(vid) or VehiclePosition(vehicle_id=vid)
                row.lat, row.lng, row.heading, row.fix_at, row.updated_at = pos["lat"], pos["lng"], pos["heading"], pos["at"], now
                s.add(row)

            for sid, vid, status in active:
                pos = positions.get(vid)
                if not pos or domain.RANK[status] < domain.RANK["dispatched"]:
                    continue  # no breadcrumb trail while the truck is parked at the plant
                last = self._last_point.get(sid)
                if last and (pos["at"] <= last[2] or
                             domain.haversine_m(last[0], last[1], pos["lat"], pos["lng"]) < self.s.trail_min_move_meters):
                    continue
                s.add(TrackPoint(shipment_id=sid, lat=pos["lat"], lng=pos["lng"], at=pos["at"]))
                self._last_point[sid] = (pos["lat"], pos["lng"], pos["at"])

            if self._last_purge is None or now - self._last_purge > timedelta(hours=1):
                await s.execute(delete(TrackPoint).where(TrackPoint.at < now - timedelta(days=self.s.trail_retention_days)))
                await s.execute(delete(LoginAttempt).where(LoginAttempt.at < now - timedelta(seconds=self.s.login_window_seconds)))
                self._last_purge = now
            await s.commit()

        # forget breadcrumbs cache for shipments that are no longer active
        active_ids = {sid for sid, _, _ in active}
        for sid in list(self._last_point):
            if sid not in active_ids:
                self._last_point.pop(sid, None)


def last_ok(state: SyncState | None) -> datetime | None:
    return as_utc(state.ok_at) if state else None
