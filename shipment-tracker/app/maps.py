"""Same-origin proxy for Ola Maps vector tiles.

The browser's map (MapLibre) rewrites every https://api.olamaps.io/... request to
/olamaps/... ; this route adds the API key server-side, so the key is never exposed and the
page CSP can stay at connect-src 'self'. Only signed-in users can use it (no open proxy),
and a small in-memory LRU cache keeps repeat tile loads off the Ola quota.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .auth import Principal, current_user
from .config import get_settings

log = logging.getLogger("tracker.maps")
router = APIRouter(tags=["maps"])

OLA_BASE = "https://api.olamaps.io"
_ALLOWED_PREFIXES = ("tiles/",)
_PASS_HEADERS = ("content-type", "etag", "last-modified")


class _LRU:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self.size = 0
        self.items: OrderedDict[str, tuple[int, bytes, dict]] = OrderedDict()

    def get(self, key: str):
        hit = self.items.get(key)
        if hit:
            self.items.move_to_end(key)
        return hit

    def put(self, key: str, value: tuple[int, bytes, dict]) -> None:
        if len(value[1]) > self.max_bytes // 20:
            return
        if key in self.items:
            self.size -= len(self.items.pop(key)[1])
        self.items[key] = value
        self.size += len(value[1])
        while self.size > self.max_bytes and self.items:
            _, old = self.items.popitem(last=False)
            self.size -= len(old[1])


_cache = _LRU(max_bytes=64 * 1024 * 1024)
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=OLA_BASE, timeout=httpx.Timeout(20, connect=8),
                                    headers={"user-agent": "where-is-my-load/1.0"})
    return _client


async def close() -> None:
    if _client is not None:
        await _client.aclose()


@router.get("/olamaps/{path:path}", include_in_schema=False)
async def ola_proxy(path: str, request: Request, _: Principal = Depends(current_user)):
    s = get_settings()
    if not path.startswith(_ALLOWED_PREFIXES) or ".." in path:
        raise HTTPException(404)
    if not s.ola_maps_api_key:
        raise HTTPException(503, "Map key not configured")
    params = [(k, v) for k, v in request.query_params.multi_items() if k.lower() != "api_key"]
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params))
    hit = _cache.get(key)
    if hit is None:
        try:
            r = await _http().get("/" + path, params=params + [("api_key", s.ola_maps_api_key)])
        except httpx.HTTPError as e:
            log.warning("ola maps request failed: %s", e)
            raise HTTPException(502, "Map service unreachable")
        headers = {h: r.headers[h] for h in _PASS_HEADERS if h in r.headers}
        hit = (r.status_code, r.content, headers)
        if r.status_code == 200:
            _cache.put(key, hit)
        elif r.status_code in (401, 403):
            log.error("Ola Maps rejected the API key (HTTP %s): %s", r.status_code, r.text[:200])
    status, body, headers = hit
    if status == 200:
        style = path.endswith("style.json")
        headers["cache-control"] = f"private, max-age={3600 if style else 604800}"
    return Response(content=body, status_code=status, headers=headers)
