"""Client for external.balajitransports.in. Holds the service-account JWT server-side only."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from datetime import date
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("tracker.upstream")

LOGIN_PATH = "/api/WebLogin"
LOCATIONS_PATH = "/api/LoconavAndIntanglesCurrentLoc"
SHIPMENTS_PATH = "/api/SearchonDateforRakeGCDetails/GetPPDTurnAroundTimeOfVeh"
WHATSAPP_PATH = "/api/WhatseraAPI/SendWhatsAppMessage"


class UpstreamError(RuntimeError):
    pass


def _jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:  # noqa: BLE001 - opaque token is fine, we fall back to a TTL
        return 0.0


class UpstreamClient:
    def __init__(self) -> None:
        s = get_settings()
        self._s = s
        self._http = httpx.AsyncClient(
            base_url=s.upstream_base_url,
            timeout=httpx.Timeout(s.upstream_timeout_seconds, connect=10.0),
            headers={"accept": "application/json, text/plain, */*", "user-agent": "where-is-my-load/1.0"},
        )
        self._token: str | None = None
        self._exp = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._http.aclose()

    async def _login(self) -> None:
        r = await self._http.post(
            LOGIN_PATH,
            params={"Username": self._s.upstream_username, "password": self._s.upstream_password},
            content=b"",
        )
        if r.status_code != 200:
            raise UpstreamError(f"login HTTP {r.status_code}")
        body = r.json()
        token = body.get("token") if isinstance(body, dict) else None
        if not body.get("success") or not token:
            raise UpstreamError(f"login rejected: {body.get('message', 'no message')}")
        self._token = token
        self._exp = _jwt_exp(token) or (time.time() + 3600)
        log.info("upstream login ok; token valid for %.0f min", (self._exp - time.time()) / 60)

    async def _get_token(self, stale: str | None = None) -> str:
        async with self._lock:
            needs = self._token is None or time.time() > self._exp - 300
            if stale is not None and self._token == stale:
                needs = True  # the token we used was rejected and nobody has refreshed it yet
            if needs:
                await self._login()
            assert self._token
            return self._token

    async def _get_list(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        last_err: Exception | None = None
        stale: str | None = None
        for attempt in range(4):
            token = await self._get_token(stale)
            stale = None
            try:
                r = await self._http.get(path, params=params, headers={"authorization": f"Bearer {token}"})
            except httpx.TransportError as e:
                last_err = e
                await asyncio.sleep(min(2 ** attempt, 10))
                continue
            if r.status_code == 401:
                stale = token
                last_err = UpstreamError("401 from upstream")
                continue
            if r.status_code >= 500 or r.status_code == 429:
                last_err = UpstreamError(f"HTTP {r.status_code}")
                await asyncio.sleep(min(2 ** attempt, 10))
                continue
            if r.status_code != 200:
                raise UpstreamError(f"GET {path} HTTP {r.status_code}")
            data = r.json()
            if isinstance(data, str):
                # The upstream (ASP.NET) returns a JSON-encoded string when Accept is strictly
                # application/json, i.e. the payload is serialised twice. Unwrap it.
                data = json.loads(data)
            if not isinstance(data, list):
                raise UpstreamError(f"GET {path}: expected a list, got {type(data).__name__}")
            return data
        raise UpstreamError(f"GET {path} failed after retries: {last_err}")

    async def fetch_locations(self) -> list[dict[str, Any]]:
        params = {k: "" for k in ("Vehicle", "Driver", "VehicleType", "Location", "feet25", "feet40", "VehicleCategory")}
        return await self._get_list(LOCATIONS_PATH, params)

    async def send_whatsapp(self, phones: list[str], message: str) -> None:
        if not phones:
            return
        token = await self._get_token()
        try:
            r = await self._http.post(
                WHATSAPP_PATH,
                json={"phoneNumber": phones, "message": message},
                headers={"authorization": f"Bearer {token}"},
            )
            if r.status_code not in (200, 201, 202):
                log.warning("WhatsApp send HTTP %s: %s", r.status_code, r.text[:200])
            else:
                log.info("WhatsApp sent to %d number(s)", len(phones))
        except Exception:
            log.exception("WhatsApp send failed")

    async def fetch_shipments(self, start: date, end: date, vehicle_id: int | None = None) -> list[dict[str, Any]]:
        params = {"From": start.isoformat(), "To": end.isoformat(), "VehicleId": "" if vehicle_id is None else str(vehicle_id)}
        return await self._get_list(SHIPMENTS_PATH, params)
