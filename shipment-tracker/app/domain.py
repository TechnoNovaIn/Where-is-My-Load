"""Pure business rules for turning upstream rows into party-facing shipment state.

Route model (all loads originate at JSW Toranagallu):
  DO allocated -> plant entry -> plant exit / JSW gate out -> Tumkur checkpoint
  -> (Bangalore-side entry) -> unloading point reached -> unloaded
After unloading the truck runs a return leg (BLRLeft, TMKReEntry...). The upstream
feed sometimes skips `unloadedTime`. For shipments older than 7 days, return-leg
stamps are used to infer delivery; recent ones keep their milestone status to
match the live TAT report.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

STATUS_ORDER = ["assigned", "loading", "dispatched", "in_transit", "near_destination", "arrived", "delivered"]
RANK = {s: i for i, s in enumerate(STATUS_ORDER)}

STATUS_LABEL = {
    "assigned": "Truck assigned",
    "loading": "Loading at plant",
    "dispatched": "Dispatched",
    "in_transit": "In transit",
    "near_destination": "Near destination",
    "arrived": "At unloading point",
    "delivered": "Delivered",
}

MILESTONE_FIELDS = (
    "DOAllocatedDate", "PlantEntrydate", "PlantExitDate", "JSWLeft",
    "TMKEntry", "TMKLeft", "BLREntry", "unloadLocReachedTime", "unloadedTime",
)
RETURN_FIELDS = ("BLRLeft", "TMKReEntryFromBLR", "TMKReEntry", "JSWReEntryDate", "ParkingReEntryDate")
HUB_CITY = "tumkur"

# Rough India bounding box; anything outside is a bad GPS fix.
_LAT_RANGE = (6.0, 37.5)
_LNG_RANGE = (68.0, 97.5)

_JUNK_PHONES = {"1234567890", "0123456789", "9876543210"}


# ---------------------------------------------------------------- timestamps
def parse_ts(value: Any) -> datetime | None:
    """Upstream timestamps are naive IST. Epoch placeholders (1970-01-01T05:30) mean 'unknown'."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    if dt.year < 2000:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC)  # store and compare in UTC; the browser renders IST


def iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- cleaning
def norm_party(name: Any) -> str:
    """Normalisation key for matching upstream PartyName spellings to the party master."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())


def clean_phones(value: Any) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[,/;|]+", str(value or "")):
        digits = re.sub(r"\D", "", part)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if (
            len(digits) == 10
            and digits[0] in "6789"
            and digits not in _JUNK_PHONES
            and len(set(digits)) > 2
            and digits not in out
        ):
            out.append(digits)
    return out


def clean_driver_name(value: Any) -> str:
    name = re.sub(r"\s*-\s*\d+\s*$", "", str(value or "")).strip()
    name = re.sub(r"\s+", " ", name)
    if not name or name.isdigit():
        return ""
    return name.title()


def format_plate(value: Any) -> str:
    raw = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    m = re.match(r"^([A-Z]{2})(\d{1,2})([A-Z]{0,3})(\d{1,4})", raw)
    if not m:
        return str(value or "").strip()
    state, dist, series, num = m.groups()
    return " ".join(p for p in (state, dist.zfill(2), series, num.zfill(4)) if p)


def is_hub_destination(destination: str | None) -> bool:
    return (destination or "").strip().casefold() == HUB_CITY


# ---------------------------------------------------------------- status
def derive_status(raw: dict[str, Any]) -> tuple[str, datetime | None, bool]:
    """Return (status, when it was reached, delivered_inferred).

    Delivery is confirmed only when upstream sets unloadedTime.  For shipments
    older than 7 days we also accept return-leg timestamps (BLRLeft, TMK re-entry,
    etc.) because the upstream often omits unloadedTime on completed trips.
    Recent shipments (within LOOKBACK_DAYS) keep their milestone status to match
    the live TAT report.
    """
    from .config import get_settings
    t = {k: parse_ts(raw.get(k)) for k in MILESTONE_FIELDS}
    if t["unloadedTime"]:
        return "delivered", t["unloadedTime"], False
    returns = [ts for ts in (parse_ts(raw.get(k)) for k in RETURN_FIELDS) if ts]
    if returns:
        ship_date = str(raw.get("ShipmentDate") or "")[:10]
        try:
            age = (datetime.now(IST).date() - date.fromisoformat(ship_date)).days
        except ValueError:
            age = 999
        if age > get_settings().lookback_days:
            return "delivered", min(returns), True
    if t["unloadLocReachedTime"]:
        return "arrived", t["unloadLocReachedTime"], False
    hub_dest = is_hub_destination(raw.get("TO"))
    if t["BLREntry"] and not hub_dest:
        return "near_destination", t["BLREntry"], False
    if t["TMKEntry"] or t["TMKLeft"]:
        return ("near_destination" if hub_dest else "in_transit"), (t["TMKEntry"] or t["TMKLeft"]), False
    if t["JSWLeft"] or t["PlantExitDate"]:
        return "dispatched", (t["JSWLeft"] or t["PlantExitDate"]), False
    if t["PlantEntrydate"]:
        return "loading", t["PlantEntrydate"], False
    return "assigned", (t["DOAllocatedDate"] or parse_ts(raw.get("ShipmentDate"))), False


def status_sentence(status: str, destination: str, site: str, inferred: bool = False) -> str:
    place = site or destination or "destination"
    city = destination or "destination"
    return {
        "assigned": "Truck assigned, waiting to load at Toranagallu",
        "loading": "Loading at JSW Toranagallu",
        "dispatched": f"On the way to {city}",
        "in_transit": f"Past Tumkur, heading to {city}",
        "near_destination": f"Close to {city}",
        "arrived": f"At {place}, waiting to unload",
        "delivered": "Delivered" + (" (truck has left your site)" if inferred else ""),
    }[status]


def build_timeline(fields: dict[str, Any], destination: str, status: str,
                   inferred: bool, status_at: datetime | None) -> list[dict[str, Any]]:
    hub_dest = is_hub_destination(destination)
    steps: list[tuple[str, str, tuple[str, ...], int]] = [
        ("assigned", "Truck assigned", ("DOAllocatedDate",), RANK["assigned"]),
        ("loading", "Entered plant for loading", ("PlantEntrydate",), RANK["loading"]),
        ("dispatched", "Loaded and left Toranagallu", ("JSWLeft", "PlantExitDate"), RANK["dispatched"]),
    ]
    if hub_dest:
        steps.append(("hub", "Reached Tumkur", ("TMKEntry", "TMKLeft"), RANK["near_destination"]))
    else:
        steps.append(("hub", "Passed Tumkur", ("TMKEntry", "TMKLeft"), RANK["in_transit"]))
        steps.append(("city", f"Entered {destination or 'destination'} side", ("BLREntry",), RANK["near_destination"]))
    steps += [
        ("arrived", "Reached unloading point", ("unloadLocReachedTime",), RANK["arrived"]),
        ("delivered", "Unloaded", ("unloadedTime",), RANK["delivered"]),
    ]

    current = RANK[status]
    out: list[dict[str, Any]] = []
    for key, label, keys, rank in steps:
        at = next((ts for ts in (parse_ts(fields.get(k)) for k in keys) if ts), None)
        note = None
        if key == "delivered" and status == "delivered" and at is None:
            at = status_at
            note = "Confirmed when the truck left your site" if inferred else None
        state = "done" if (at is not None or current >= rank) else "pending"
        out.append({"key": key, "label": label, "at": iso_utc(at), "state": state, "note": note})

    if status != "delivered":
        done_idx = [i for i, s in enumerate(out) if s["state"] == "done"]
        if done_idx:
            out[done_idx[-1]]["state"] = "current"
    return out


# ---------------------------------------------------------------- GPS
def parse_position(loc: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat = float(loc.get("lat"))
        lng = float(loc.get("lng"))
    except (TypeError, ValueError):
        return None
    if not (_LAT_RANGE[0] <= lat <= _LAT_RANGE[1] and _LNG_RANGE[0] <= lng <= _LNG_RANGE[1]):
        return None
    at = parse_ts(loc.get("TimeStamp"))
    if at is None:  # coordinate with no usable fix time cannot be trusted as "current"
        return None
    heading = loc.get("Heading")
    try:
        heading = float(heading) % 360 if heading is not None else None
    except (TypeError, ValueError):
        heading = None
    return {"lat": round(lat, 6), "lng": round(lng, 6), "heading": heading, "at": at}


def haversine_m(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lng - a_lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ---------------------------------------------------------------- notifications
def notification_text(status: str, plate: str, product: str, destination: str,
                      site: str, inferred: bool = False, new: bool = False) -> tuple[str, str]:
    load = product or "load"
    place = site or destination or "your site"
    if new:
        return f"New shipment on {plate}", f"{load} for {place}. Truck assigned at Toranagallu."
    return {
        "assigned": (f"Truck assigned: {plate}", f"{load} for {place}."),
        "loading": (f"{plate} is loading", f"Your {load} is being loaded at JSW Toranagallu."),
        "dispatched": (f"{plate} dispatched", f"Your {load} has left Toranagallu for {destination}."),
        "in_transit": (f"{plate} passed Tumkur", f"Heading to {destination}."),
        "near_destination": (f"{plate} is close", f"Approaching {destination}."),
        "arrived": (f"{plate} reached {place}", "The truck is at the unloading point."),
        "delivered": (
            f"{plate} delivered",
            f"{load} delivered at {place}." + (" Confirmed from the truck's return trip." if inferred else ""),
        ),
    }[status]
