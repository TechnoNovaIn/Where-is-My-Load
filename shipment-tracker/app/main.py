from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from . import admin, api, auth, contact, maps
from .config import get_settings
from .db import SessionLocal, as_utc, init_db, utcnow
from .models import SyncState
from .sync import Syncer
from .upstream import UpstreamClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("tracker")
STATIC = Path(__file__).resolve().parent.parent / "static"
import hashlib as _hl, mimetypes as _mt
_mt.add_type("application/manifest+json", ".webmanifest")
settings = get_settings()

def _asset_hash() -> str:
    h = _hl.md5()
    for f in sorted(STATIC.glob("*.js")) + sorted(STATIC.glob("*.css")):
        h.update(f.read_bytes())
    return h.hexdigest()[:8]

_ASSET_V = _asset_hash()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if not settings.cookie_secure:
        log.warning("COOKIE_SECURE is false — session cookies will be sent over cleartext. "
                     "Set COOKIE_SECURE=true before deploying over HTTPS.")
    log.info("API rate limiter and SSE connection counter are in-memory. "
             "With multiple uvicorn workers, limits apply per process.")
    client = syncer = task = None
    if settings.run_poller:
        client = UpstreamClient()
        syncer = Syncer(client)
        task = asyncio.create_task(syncer.run(), name="syncer")
        log.info("poller started")
    yield
    if syncer and task:
        syncer.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    if client:
        await client.close()
    await maps.close()


app = FastAPI(title="Where is my load (Balaji Transports)", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://cdnjs.cloudflare.com",
    "style-src 'self' https://cdnjs.cloudflare.com https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self'",          # map tiles come through /olamaps on this origin
    "worker-src 'self' blob:",     # MapLibre renders tiles in web workers
    "child-src blob:",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
])
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

_rate_hits: dict[str, deque[float]] = defaultdict(deque)

def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    q = _rate_hits[ip]
    cutoff = now - settings.api_rate_window_seconds
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= settings.api_rate_limit:
        return True
    q.append(now)
    return False


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    # CSRF: session cookie is SameSite=Strict; additionally require a header a cross-site form cannot send.
    if request.method in UNSAFE and path.startswith("/api/") and \
            request.headers.get("x-requested-with") != "fetch":
        return JSONResponse({"detail": "Missing request header"}, status_code=403)
    if path.startswith("/api/") and not path.endswith("/events"):
        ip = request.client.host if request.client else "unknown"
        if _rate_limited(ip):
            return JSONResponse({"detail": "Too many requests. Please slow down."}, status_code=429)
    response = await call_next(request)
    h = response.headers
    h.setdefault("Content-Security-Policy", CSP)
    h.setdefault("X-Content-Type-Options", "nosniff")
    # Send only the origin (never paths) to other sites.
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
    if settings.cookie_secure:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    elif request.url.path.startswith("/static/") and request.url.path.rsplit(".", 1)[-1] in ("js", "css"):
        h["Cache-Control"] = "public, max-age=86400, must-revalidate" if "v=" in str(request.url.query) else "no-cache"
    return response


if settings.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["x-requested-with"])

app.include_router(auth.router)
app.include_router(api.router)
app.include_router(admin.router)
app.include_router(maps.router)
app.include_router(contact.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


import re as _re
_ASSET_RE = _re.compile(r'(?<=["\'])(/static/(?:[a-z0-9_-]+\.(?:js|css)))(?=["\'])')

def _versioned_html(name: str):
    raw = (STATIC / name).read_text()
    html = _ASSET_RE.sub(rf"\1?v={_ASSET_V}", raw)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
async def index():
    return _versioned_html("index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return _versioned_html("admin.html")


@app.get("/login", include_in_schema=False)
async def login_page():
    return _versioned_html("login.html")


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """200 while the DB answers and both sync loops succeeded recently; 503 otherwise."""
    async with SessionLocal() as db:
        await db.execute(text("SELECT 1"))
        states = {r.key: r for r in (await db.scalars(select(SyncState))).all()}
    now = utcnow()
    limits = {"shipments": settings.shipment_poll_seconds * 5, "locations": settings.location_poll_seconds * 5}
    report, healthy = {}, True
    for key, limit in limits.items():
        st = states.get(key)
        ok_at = as_utc(st.ok_at) if st else None
        fresh = ok_at is not None and (now - ok_at).total_seconds() < limit
        healthy &= fresh
        report[key] = {"ok_at": ok_at.isoformat() if ok_at else None, "fresh": fresh,
                       "last_error": (st.error if st else "") or None}
    return JSONResponse({"ok": healthy, "sync": report}, status_code=200 if healthy else 503)
