# 🚛 Where Is My Load

Real-time shipment tracking platform for **Balaji Transports** — giving customers ("parties") live visibility into steel shipments moving from JSW Toranagallu to destinations across Karnataka and beyond.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688)
![SQLite](https://img.shields.io/badge/SQLite-WAL-003B57)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED)
![License](https://img.shields.io/badge/License-Private-red)

---

## ✨ Features

- **Live truck tracking** on an interactive map (Ola Maps + MapLibre GL JS) with GPS updates every 60 seconds
- **Status timeline** — from truck assignment → loading → dispatch → transit checkpoints → arrival → delivery
- **Instant notifications** via in-app alerts, browser push notifications, and WhatsApp messages
- **Multi-party access** — each customer sees only their own shipments, scoped by party name
- **Admin console** — user management, party name assignment, CRM contacts, full audit log
- **Mobile-first PWA** — responsive design, installable as a home-screen app
- **CSV export** of shipment data
- **Server-Sent Events (SSE)** for real-time browser updates without polling
- **Automatic delivery inference** when upstream data is incomplete

---

## 🏗️ Architecture

```
┌─────────────┐    cookie session    ┌──────────────────────┐   service JWT   ┌─────────────────────────────┐
│   Browser   │ ◄──────────────────► │  FastAPI Application │ ◄─────────────► │ external.balajitransports.in │
│ (any device)│                      │  (this application)  │                 │     (upstream API)           │
└─────────────┘                      └──────────────────────┘                 └─────────────────────────────┘
                                           │            │
                                           │            └── Ola Maps API (tiles proxied, key stays server-side)
                                           │
                                      ┌────▼────┐
                                      │ SQLite  │  (or Postgres for horizontal scaling)
                                      │   DB    │
                                      └─────────┘
```

**Key design decisions:**

- Upstream API credentials **never** reach the browser
- Ola Maps API key stays **server-side** — tiles proxied through `/olamaps/`
- Background poller fetches shipments (every 120s) and GPS positions (every 60s)
- SSE pushes notifications to browsers in real time
- SQLite (WAL mode) for single-server; swap to Postgres for multi-process

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.9+, FastAPI (async), SQLAlchemy 2.0 (async ORM) |
| **Database** | SQLite (default) / PostgreSQL via asyncpg |
| **Frontend** | Vanilla ES modules, MapLibre GL JS |
| **Maps** | Ola Maps vector tiles |
| **Auth** | bcrypt (12 rounds), JWT session cookies (HS256) |
| **HTTP Client** | httpx (async) for upstream API |
| **Containerisation** | Docker (python:3.12-slim) |

---

## 📁 Project Structure

```
shipment-tracker/
├── app/
│   ├── main.py          # FastAPI app, lifespan, middleware, security headers
│   ├── api.py           # Party-facing tracking API (shipments, notifications, SSE)
│   ├── auth.py          # Login, sessions, password management, CSRF
│   ├── admin.py         # Admin user management & audit log API
│   ├── contact.py       # Customer care / CRM contacts API
│   ├── domain.py        # Business rules: status derivation, GPS, notifications
│   ├── sync.py          # Background poller: upstream sync, GPS, trail, backups
│   ├── upstream.py      # HTTP client for Balaji Transports upstream API
│   ├── maps.py          # Ola Maps tile proxy with in-memory cache
│   ├── models.py        # SQLAlchemy ORM models
│   ├── db.py            # Database engine, session factory, auto-migration
│   ├── config.py        # Pydantic settings from environment / .env
│   └── cli.py           # CLI tools (create-admin, import-users, etc.)
├── static/              # Frontend HTML, CSS, JS, PWA assets
├── tests/               # pytest test suite
├── Dockerfile           # Production container image
├── requirements.txt     # Pinned Python dependencies
├── requirements-dev.txt # Dev dependencies (pytest)
├── run.sh               # One-command setup & start (macOS/Linux)
├── run.bat              # One-command setup & start (Windows)
└── .env                 # Environment configuration (not committed)
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- **Balaji Transports upstream API credentials** (`UPSTREAM_USERNAME`, `UPSTREAM_PASSWORD`)
- **Ola Maps API key** (optional — app works without it, map shows as unavailable)

### Automatic Setup (Recommended)

**macOS / Linux:**
```bash
cd shipment-tracker
./run.sh
```

**Windows:**
```cmd
cd shipment-tracker
run.bat
```

The script creates a virtualenv, installs dependencies, checks your `.env`, and starts the server at `http://localhost:8000`.

### Manual Setup

```bash
cd shipment-tracker

# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — fill in UPSTREAM_USERNAME, UPSTREAM_PASSWORD, SESSION_SECRET

# 4. Generate a session secret
python -c "import secrets; print(secrets.token_urlsafe(48))"

# 5. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Create the First Admin Account

```bash
.venv/bin/python -m app.cli create-admin ops.admin --password "choose-a-strong-one"
```

Then open `http://localhost:8000`, sign in, and navigate to **Users** to create party logins.

---

## ⚙️ Configuration

All settings via environment variables or `.env` file. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `UPSTREAM_USERNAME` | — | **Required.** Upstream API username |
| `UPSTREAM_PASSWORD` | — | **Required.** Upstream API password |
| `SESSION_SECRET` | — | **Required.** 32+ char random string for JWT signing |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/tracker.db` | SQLite or Postgres connection string |
| `COOKIE_SECURE` | `true` | Set `false` for local HTTP dev |
| `RUN_POLLER` | `true` | Background sync. Set `false` on scale-out web instances |
| `LOCATION_POLL_SECONDS` | `60` | GPS polling interval |
| `SHIPMENT_POLL_SECONDS` | `120` | Shipment data polling interval |
| `OLA_MAPS_API_KEY` | *(empty)* | Ola Maps key (stays server-side) |
| `WHATSAPP_ENABLED` | `true` | WhatsApp alerts via upstream API |
| `GPS_STALE_MINUTES` | `30` | GPS fix age before marking "stale" |
| `DELIVERED_VISIBLE_DAYS` | `90` | How long delivered shipments remain visible |

> See [`PRODUCT_DOCUMENTATION.md`](shipment-tracker/PRODUCT_DOCUMENTATION.md) for the full configuration reference.

---

## 👥 User Roles

| Role | Access |
|------|--------|
| **`admin`** (Balaji Transports staff) | All shipments, user management, driver contacts, audit log, CRM config |
| **`party`** (Customer) | Only their shipments (by party name), notifications, WhatsApp alerts, support contacts |

---

## 📡 API Overview

All endpoints require authentication (session cookie) unless noted.

| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/login` | Sign in |
| `GET /api/shipments` | List shipments (party-scoped, with KPI counts) |
| `GET /api/shipments/{id}` | Shipment detail with timeline & GPS trail |
| `GET /api/shipments/export.csv` | CSV export |
| `GET /api/notifications` | User notifications |
| `GET /api/events` | SSE stream for real-time updates |
| `GET /api/admin/users` | Admin: user management |
| `GET /api/admin/party-names` | Admin: upstream party names |
| `GET /api/admin/audit` | Admin: audit log |
| `GET /healthz` | Health check (200 / 503) |

> Full API reference in [`PRODUCT_DOCUMENTATION.md`](shipment-tracker/PRODUCT_DOCUMENTATION.md).

---

## 🐳 Docker

```bash
cd shipment-tracker

# Build and run
docker build -t tracker .
docker run -d --env-file .env -p 8000:8000 -v tracker-data:/srv/data tracker

# Or with docker compose
docker compose up -d --build
```

The image runs a single uvicorn worker with a built-in health check on `/healthz`.

---

## 🧪 Testing

```bash
cd shipment-tracker
pip install -r requirements-dev.txt
pytest
```

---

## 🔒 Security

- **bcrypt** password hashing (12 rounds), min 10 chars, 5 distinct characters required
- **JWT** session cookies: `HttpOnly`, `SameSite=Strict`, `Secure`
- **CSRF** protection via `X-Requested-With: fetch` header requirement
- **Login throttling**: 8 attempts / 15 min per IP+username (DB-backed, survives restarts)
- **Rate limiting**: 120 requests / 60s per IP on API endpoints
- **Security headers**: CSP, HSTS, X-Frame-Options DENY, nosniff, Permissions-Policy
- **Token versioning**: disabling a user or resetting their password immediately invalidates all sessions

---

## 🚀 Production Checklist

- [ ] Serve behind **nginx/Caddy** with TLS; keep `COOKIE_SECURE=true`
- [ ] Run uvicorn with `--proxy-headers` only behind your own reverse proxy
- [ ] Run exactly **one worker** (poller is in-process); scale with `RUN_POLLER=false` + Postgres
- [ ] Add rate limiting on `/api/auth/login` at the proxy level
- [ ] Configure nginx for SSE: `proxy_buffering off; proxy_read_timeout 1h;` on `/api/events`
- [ ] Set `OLA_MAPS_API_KEY` for the live map
- [ ] Automated backups enabled by default (SQLite online backup every 6 hours, keeps last 5)

---

## 📖 Documentation

For comprehensive product documentation including the full status lifecycle, party name matching system, WhatsApp integration, CLI tools, deployment guide, and troubleshooting:

📄 **[`shipment-tracker/PRODUCT_DOCUMENTATION.md`](shipment-tracker/PRODUCT_DOCUMENTATION.md)**

---

## 🤝 CLI Tools

```bash
python -m app.cli <command>
```

| Command | Description |
|---------|-------------|
| `create-admin <user>` | Create / update an admin account |
| `import-users <csv>` | Bulk import users from CSV |
| `reset-password <user>` | Reset a user's password |
| `disable-user <user>` | Disable an account (signs them out) |
| `enable-user <user>` | Re-enable an account |
| `unassigned` | List party names with no login assigned |
| `template <out.csv>` | Generate a starter CSV from upstream party names |
