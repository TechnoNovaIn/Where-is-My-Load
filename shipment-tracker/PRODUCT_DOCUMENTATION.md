# Where Is My Load — Product Documentation

**Balaji Transports Shipment Tracking Platform**
Version 1.0 | Last updated: October 2026

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Installation & Setup](#4-installation--setup)
5. [Running the Application](#5-running-the-application)
6. [Configuration Reference](#6-configuration-reference)
7. [User Roles & Access Control](#7-user-roles--access-control)
8. [User Management (Admin Console)](#8-user-management-admin-console)
9. [Party Name System](#9-party-name-system)
10. [Shipment Tracking](#10-shipment-tracking)
11. [Status Rules & Lifecycle](#11-status-rules--lifecycle)
12. [Live Map (Ola Maps)](#12-live-map-ola-maps)
13. [Notifications & Alerts](#13-notifications--alerts)
14. [WhatsApp Integration](#14-whatsapp-integration)
15. [Customer Care Contacts (CRM)](#15-customer-care-contacts-crm)
16. [Authentication & Security](#16-authentication--security)
17. [CLI Tools](#17-cli-tools)
18. [API Reference](#18-api-reference)
19. [Database](#19-database)
20. [Deployment (Docker)](#20-deployment-docker)
21. [Production Checklist](#21-production-checklist)
22. [Monitoring & Health Checks](#22-monitoring--health-checks)
23. [Mobile & PWA Support](#23-mobile--pwa-support)
24. [Theming](#24-theming)
25. [Troubleshooting](#25-troubleshooting)
26. [Project File Structure](#26-project-file-structure)

---

## 1. Product Overview

**"Where is my load?"** is a real-time shipment tracking platform built for Balaji Transports. It gives their customers (called "parties") live visibility into steel shipments moving from JSW Toranagallu to unloading points across Karnataka and beyond.

### What it does

- **Live truck tracking** on an interactive map with GPS positions updated every 60 seconds
- **Status timeline** from truck assignment through loading, dispatch, transit checkpoints, arrival and delivery
- **Instant notifications** via in-app alerts, browser notifications and WhatsApp messages at every status change
- **Multi-party access** — each customer sees only their own shipments, identified by party name
- **Admin console** for Balaji Transports staff to manage user logins, assign party names, configure support contacts and audit all changes
- **Mobile-responsive** design that works on phones, tablets and desktops; installable as a home-screen app (PWA)

### Who uses it

| User | Role | What they see |
|------|------|---------------|
| Balaji Transports staff | `admin` | All shipments across all parties, user management console, driver contact numbers |
| Customers (steel buyers) | `party` | Only shipments for their assigned party names, support team contact, notifications |

---

## 2. Architecture

```
┌─────────────┐     cookie session     ┌──────────────────────┐    service JWT    ┌────────────────────────────┐
│   Browser    │ ◄─────────────────────► │  FastAPI Application  │ ◄───────────────► │ external.balajitransports.in│
│  (any device)│                         │   (this application)  │                   │   (upstream API)            │
└─────────────┘                         └──────────────────────┘                   └────────────────────────────┘
                                              │            │
                                              │            └─── Ola Maps API (tiles proxied, key stays server-side)
                                              │
                                         ┌────▼────┐
                                         │ SQLite  │  (or Postgres for multi-process deployments)
                                         │ Database│
                                         └─────────┘
```

### Key design decisions

- **Upstream credentials never reach the browser.** The server authenticates with the upstream API using a service JWT and proxies all data.
- **Ola Maps API key stays server-side.** Map tiles are loaded through `/olamaps/...` on this server. The browser never sees the API key.
- **Background poller** fetches shipment data every 120 seconds and GPS positions every 60 seconds. Exactly one poller runs per deployment.
- **Server-sent events (SSE)** push notifications to the browser in real time — no polling from the client.
- **SQLite with WAL mode** for single-server deployments; swap to Postgres for horizontal scaling.

### Technology stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.9+, FastAPI (async), SQLAlchemy 2.0 (async ORM) |
| Database | SQLite (default) or PostgreSQL via asyncpg |
| Frontend | Vanilla ES modules (no framework), MapLibre GL JS |
| Maps | Ola Maps vector tiles |
| Auth | bcrypt password hashing, JWT session cookies (HS256) |
| HTTP client | httpx (async) for upstream API calls |

---

## 3. Prerequisites

- **Python 3.9 or later** (tested with 3.9, 3.12 and 3.14)
- **Balaji Transports upstream API credentials** (`UPSTREAM_USERNAME` and `UPSTREAM_PASSWORD`)
- **Ola Maps API key** (optional — the app works without it, but the map shows as unavailable)
- **pip** (Python package installer)

---

## 4. Installation & Setup

### Automatic setup (recommended)

**macOS / Linux:**
```bash
./run.sh
```

**Windows:**
```
run.bat
```

The script:
1. Copies `.env.example` to `.env` if `.env` doesn't exist
2. Creates a Python virtual environment in `.venv/`
3. Installs all dependencies from `requirements.txt`
4. Generates a `SESSION_SECRET` if missing
5. Checks that upstream credentials are filled in
6. Starts the server on `http://localhost:8000`

On the first run, the script stops after creating `.env` and asks you to fill in the required values.

### Manual setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create .env from the example
cp .env.example .env

# 4. Edit .env — fill in required values (see Section 6)

# 5. Generate a session secret
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste the output as SESSION_SECRET= in .env

# 6. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Create the first admin account

After the server is running, open a second terminal:

```bash
# Linux/macOS
.venv/bin/python -m app.cli create-admin ops.admin --password "choose-a-strong-one"

# Windows
.venv\Scripts\python -m app.cli create-admin ops.admin --password "choose-a-strong-one"
```

Now open `http://localhost:8000`, sign in as the admin, and navigate to **Users** to start creating party logins.

---

## 5. Running the Application

### Development mode (with auto-reload)

```bash
uvicorn app.main:app --reload --port 8000
```

> **Note:** Set `COOKIE_SECURE=false` in `.env` when running over plain HTTP (localhost). Without this, the session cookie won't be set and sign-in will fail silently.

### Production mode

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
```

> Always run exactly **one worker** because the background poller and login throttle live in-process. To scale horizontally, use Postgres and add web-only containers with `RUN_POLLER=false`.

### Docker

```bash
# Build and run
docker compose up -d

# Or manually
docker build -t tracker .
docker run -d --env-file .env -p 8000:8000 -v tracker-data:/srv/data tracker
```

### Stopping a running server

If the server crashes and leaves port 8000 occupied:

```bash
lsof -ti:8000 | xargs kill -9
```

---

## 6. Configuration Reference

All configuration is via environment variables, read from a `.env` file in the project root.

### Required

| Variable | Description |
|----------|-------------|
| `UPSTREAM_USERNAME` | Balaji Transports upstream API username |
| `UPSTREAM_PASSWORD` | Upstream API password (may contain special characters) |
| `SESSION_SECRET` | Random string, minimum 32 characters. Used to sign JWT session cookies. Generate with: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |

### Storage

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/tracker.db` | SQLite for single box; Postgres: `postgresql+asyncpg://user:pass@host:5432/tracker` |

### Session & cookies

| Variable | Default | Description |
|----------|---------|-------------|
| `SESSION_TTL_HOURS` | `12` | How long a login session lasts |
| `COOKIE_SECURE` | `true` | Set `false` for local HTTP testing. Must be `true` in production (HTTPS) |
| `COOKIE_NAME` | `bt_session` | Name of the session cookie |

### Background sync

| Variable | Default | Description |
|----------|---------|-------------|
| `RUN_POLLER` | `true` | Enable the background poller. Set `false` on web-only scale-out instances |
| `LOCATION_POLL_SECONDS` | `60` | GPS position polling interval |
| `SHIPMENT_POLL_SECONDS` | `120` | Shipment data polling interval |
| `LOOKBACK_DAYS` | `10` | How many days of shipments to fetch each poll cycle |
| `STRAGGLER_LIMIT` | `25` | Max older active shipments to refresh per cycle |

### WhatsApp

| Variable | Default | Description |
|----------|---------|-------------|
| `WHATSAPP_ENABLED` | `true` | Send WhatsApp alerts via the upstream API |

### Tracking behaviour

| Variable | Default | Description |
|----------|---------|-------------|
| `GPS_STALE_MINUTES` | `30` | After this many minutes without a GPS fix, the position is marked "stale" (faded on the map, labelled "weak signal") |
| `TRAIL_MIN_MOVE_METERS` | `75.0` | Minimum distance a truck must move before a new breadcrumb is added to the trail |
| `TRAIL_RETENTION_DAYS` | `30` | Trail points older than this are purged |
| `DELIVERED_VISIBLE_DAYS` | `90` | Delivered shipments remain visible for this many days |

### Ola Maps

| Variable | Default | Description |
|----------|---------|-------------|
| `OLA_MAPS_API_KEY` | *(empty)* | API key from maps.olakrutrim.com. Stays on the server; the browser loads tiles through `/olamaps/` |
| `OLA_STYLE_LIGHT` | `default-light-standard` | Light theme map style name |
| `OLA_STYLE_DARK` | `default-dark-standard` | Dark theme map style name |

### Login throttling

| Variable | Default | Description |
|----------|---------|-------------|
| `LOGIN_MAX_ATTEMPTS` | `8` | Maximum failed login attempts per IP+username |
| `LOGIN_WINDOW_SECONDS` | `900` | Sliding window (15 minutes) before the counter resets |

### Upstream API

| Variable | Default | Description |
|----------|---------|-------------|
| `UPSTREAM_BASE_URL` | `https://external.balajitransports.in` | Base URL of the upstream API |
| `UPSTREAM_TIMEOUT_SECONDS` | `30.0` | HTTP timeout for upstream requests |

---

## 7. User Roles & Access Control

### Role: `party` (Customer)

- Sees shipments only for their assigned party names
- Gets real-time notifications (in-app + WhatsApp) on status changes
- Can change their own password
- Can switch between dark and light theme
- Sees customer care contact in the header, on each shipment, and on the login page

### Role: `admin` (Balaji Transports Staff)

- Sees all shipments across all parties (party name shown on every row)
- Full access to the user management console (`/admin`)
- Can create, edit, disable and delete user accounts
- Can assign and unassign party names to users
- Can reset user passwords (generates temporary passwords)
- Can configure customer care contacts
- Can view the full audit log
- Does **not** receive notifications (admins see everything directly)
- Sees driver phone numbers (labelled "staff only")

### Access rules

- Unauthenticated users can only see the login page and the public contact endpoint
- Session cookies are `HttpOnly`, `SameSite=Strict`, and `Secure` (in production)
- Token version tracking: disabling a user, changing their role, or resetting their password immediately invalidates all their sessions

---

## 8. User Management (Admin Console)

The admin console is at `/admin` and has four tabs:

### Users tab

- **Create user**: Username (lowercase, 3-64 chars), contact name, company, email, phone, role, party names, WhatsApp alerts toggle
- **Edit user**: Click any row to open the editor drawer. Change profile fields, role, active status, party names
- **Reset password**: Generates a temporary password shown once in a copyable dialog. The user must set their own on next login.
- **Disable/Enable**: Disabling a user signs them out everywhere immediately (via token version bump)
- **Delete**: Permanently removes the account. Offers "Disable" as a non-destructive alternative.
- **Search & filter**: Search by username, company or party name. Filter by All / Active / Disabled / Administrators.

### Party Names tab

- Lists every `PartyName` value seen in upstream shipments
- Shows counts: active shipments, total shipments, last shipment date
- Shows which logins track each party name
- Filter to party names with no login assigned
- One-click "Create login" to make a new user pre-assigned to that party name

### Activity tab

- Full audit log of every change to the user master
- Records: who made the change, what was changed, on which user, when
- Tracks: user creation, updates, password resets, deletions, customer care contact changes, password self-changes

### Customer Care tab

- Manage support team contacts that party users see everywhere
- Each contact has: label/name, phone, alternate phone, email, hours, WhatsApp toggle
- Add multiple contacts (e.g., "Logistics Desk" and "Customer care")
- Live preview of how the contact card appears to party users
- Changes are recorded in the Activity audit log

---

## 9. Party Name System

### How it works

1. The upstream API sends shipments with a `PartyName` field (e.g., "JSW STEEL LIMITED", "SAGITTARIUS METAL")
2. The system normalises each party name into a `party_key` by stripping all non-alphanumeric characters and lowercasing (e.g., "JSW STEEL LIMITED" → `jswsteellimited`)
3. Each user has a list of party names, each also stored with its normalised `party_key`
4. When a user loads the tracking page, the system filters shipments where `shipment.party_key` matches any of the user's `party_keys`

### Matching rules

- **Case-insensitive**: "JSW Steel" and "jsw steel" match
- **Punctuation-insensitive**: "T.T.P. Technologies (P) Ltd" and "TTP Technologies P Ltd" match
- **Space-insensitive**: "JSW STEEL" and "JSWSTEEL" match

### Adding party names

**From existing shipments (most common):**
1. Go to `/admin` → Party Names tab
2. Search for the party name
3. Click "Create login" or add it to an existing user

**Custom party names (before shipments exist):**
1. Open a user's editor
2. Scroll to the party names section
3. Type the exact `PartyName` text in the "Or type an exact PartyName not seen yet" field
4. Click "Add"

**Multi-party logins:**
One user can track multiple party names (e.g., a group company with several subsidiaries). One party name can also be tracked by multiple users.

---

## 10. Shipment Tracking

### Tracking page (`/`)

The main tracking page has two sections:

**Left panel — Shipment list:**
- **KPI strip** at the top: At plant | In transit | At site | Delivered today
- **Tabs**: "On the way" (active shipments) and "Delivered" (past 90 days)
- **Search**: Filter by truck number, product, site, destination or party name
- **Party filter**: For users with multiple party names, a dropdown to filter by one
- Each card shows: party name (if multiple), vehicle plate, status badge, product, weight, destination, GPS age

**Right panel — Live map:**
- MapLibre GL JS rendering Ola Maps vector tiles
- Truck pins colour-coded by status:
  - Grey: at plant (assigned/loading)
  - Amber: dispatched / in transit
  - Teal: near destination / at unloading point
- Arrow pins for moving trucks (heading direction), truck icons for stopped
- Faded/dashed pins for stale GPS (30+ minutes without update)
- "Fit all trucks" button to zoom to all positions
- Map legend with colour and symbol explanations

### Shipment detail view

Click any shipment to open the detail view:

- **Vehicle plate and status badge**
- **Status sentence** (e.g., "Past Tumkur, heading to Bangalore")
- **GPS status**: "Live, 2 min ago" / "Weak signal, last 35 min ago" / "No signal yet"
- **Driver phone** (admin/staff only) — tap to call
- **Support team contact** (party users) — with "quote shipment #..." for follow-ups
- **Shipment facts**: load (product, weight), origin, destination, dispatch date
- **Progress timeline**: step-by-step milestone list (assigned → loading → dispatched → in transit → near destination → at unloading point → delivered) with timestamps
- **Route trail** on the map: blue line showing the truck's path

---

## 11. Status Rules & Lifecycle

Shipment status is derived from upstream milestone timestamps. Statuses progress forward and **never move backwards**.

| Status | Party sees | Upstream evidence |
|--------|-----------|-------------------|
| `assigned` | Truck assigned | `DOAllocatedDate` |
| `loading` | Loading at plant | `PlantEntrydate` |
| `dispatched` | Dispatched | `PlantExitDate` or `JSWLeft` |
| `in_transit` | In transit | `TMKEntry` / `TMKLeft` (Tumkur checkpoint) |
| `near_destination` | Near destination | `BLREntry`; for Tumkur deliveries, `TMKEntry` |
| `arrived` | At unloading point | `unloadLocReachedTime` |
| `delivered` | Delivered | `unloadedTime`, **or** any return-leg stamp, **or** the same truck was assigned a newer load |

### Special delivery rules

The upstream feed often omits the `unloadedTime` timestamp, so two fallback rules exist:

1. **Return-leg inference**: If the truck shows a return-leg timestamp (`BLRLeft`, `TMKReEntry`, `TMKReEntryFromBLR`, `JSWReEntryDate`, `ParkingReEntryDate`), the shipment is marked as delivered. Shown to the party as: *"Confirmed when the truck left your site"*

2. **Supersede rule**: If the same vehicle is assigned a newer shipment (higher ShipmentID), older open shipments on that vehicle are automatically marked as delivered. This prevents a party from seeing a truck on someone else's trip.

### Route model

All loads originate at **JSW Toranagallu**. The typical route:

```
DO allocated → Plant entry → Plant exit / JSW gate out → Tumkur checkpoint
→ (Bangalore-side entry) → Unloading point reached → Unloaded
```

After unloading, the truck runs a return leg back through the checkpoints.

### GPS rules

- Coordinates outside India (lat 6-37.5, lng 68-97.5) are discarded
- The `1970-01-01T05:30` placeholder timestamp means "unknown" and is discarded
- Positions without a usable fix timestamp are discarded
- Fixes older than `GPS_STALE_MINUTES` (default: 30) are drawn faded and labelled "weak signal"
- Placeholder driver numbers (`1234567890`, `0123456789`, etc.) show as "not on record"
- Trail breadcrumbs are only added when the truck moves more than 75 metres

---

## 12. Live Map (Ola Maps)

### How it works

- **Map tiles** are Ola Maps vector tiles rendered with MapLibre GL JS
- **Tile proxy**: All tile requests go through `/olamaps/...` on this server. The server adds the `api_key` parameter server-side, so the key never reaches the browser
- **In-memory cache**: A 64 MB LRU cache keeps repeat tile loads from hitting the Ola API quota
- **Authentication**: Only signed-in users can access `/olamaps/...` — it's not an open proxy
- **CSP compliance**: The Content Security Policy restricts `connect-src` to `'self'`, so all tile traffic stays on the same origin

### Configuration

1. Get an API key from [maps.olakrutrim.com](https://maps.olakrutrim.com) → Dashboard → API keys
2. Set `OLA_MAPS_API_KEY=your-key-here` in `.env`
3. Optionally set `OLA_STYLE_LIGHT` and `OLA_STYLE_DARK` (add language suffixes like `-hi` or `-kn` for local labels)

### Without a map key

The application works fully without the Ola Maps key:
- The map panel shows "Map unavailable" with an explanation
- All shipment tracking, status updates, notifications and alerts continue to work
- Party users still see the shipment list, detail view and all contact information

---

## 13. Notifications & Alerts

### In-app notifications

- Every status advance creates a notification for each active party user tracking that party name
- The browser receives notifications via **server-sent events** (`GET /api/events`) within ~5 seconds
- The bell icon in the header shows the unread count
- Clicking a notification opens the relevant shipment
- "Mark all read" clears the unread state
- **Desktop notifications**: If the user grants browser notification permission, system notifications appear when the tab is in the background

### Notification triggers

| Event | Notification title example |
|-------|---------------------------|
| New shipment assigned | "New shipment on KA 06 AB 3469" |
| Loading started | "KA 06 AB 3469 is loading" |
| Dispatched from plant | "KA 06 AB 3469 dispatched" |
| Passed Tumkur | "KA 06 AB 3469 passed Tumkur" |
| Near destination | "KA 06 AB 3469 is close" |
| Reached unloading point | "KA 06 AB 3469 reached [site]" |
| Delivered | "KA 06 AB 3469 delivered" |

### Silent rules

- The **first sync** on an empty database is silent — parties are not flooded with historical notifications
- **Admins do not receive notifications** — they see everything directly in the tracking view

---

## 14. WhatsApp Integration

### How it works

WhatsApp alerts are sent via the Balaji Transports upstream API (`/api/WhatseraAPI/SendWhatsAppMessage`). When a shipment status changes:

1. The system identifies all active party users tracking that party name who have `whatsapp_alerts` enabled and a phone number on file
2. The phone number is normalised to the `91XXXXXXXXXX` format
3. A WhatsApp message is sent with the notification title (bold) and body

### Message format

```
*KA 06 AB 3469 dispatched*
Your GICF COIL has left Toranagallu for Bangalore.
```

### Configuration

- `WHATSAPP_ENABLED=true` in `.env` (default)
- Each user must have a valid phone number in their profile
- The "WhatsApp alerts" toggle must be enabled for the user (default: on)
- Admin can toggle WhatsApp per user from the user editor

---

## 15. Customer Care Contacts (CRM)

### Setting up contacts

1. Sign in as admin → go to `/admin` → **Customer care** tab
2. Click **+ Add contact**
3. Fill in: label, phone number, alternate number (optional), email (optional), hours (optional), WhatsApp toggle
4. Save — the contact is immediately visible to all party users

### Where contacts appear

| Location | What's shown |
|----------|-------------|
| **Header** (every page) | Gold chip with label and phone number. For multiple contacts: dropdown with all contacts showing phone, WhatsApp, email |
| **Shipment detail** | Full contact card with "quote shipment #..." text. Phone, alternate phone, WhatsApp (with pre-filled message), email (with pre-filled subject) |
| **Login page** | Help text below the sign-in form showing contact details for forgotten passwords |

### Supported phone formats

- 10-digit Indian mobile (starting with 6/7/8/9)
- Landlines with STD code (e.g., 0816 2XXXXXX)
- 1800 toll-free numbers
- Numbers with `+91` or `91` prefix are normalised automatically

---

## 16. Authentication & Security

### Password rules

- Minimum 10 characters
- Maximum 128 characters
- Must not contain the username
- Must have at least 5 distinct characters
- bcrypt hashing with 12 rounds

### Session management

- JWT tokens stored in `HttpOnly`, `SameSite=Strict`, `Secure` cookies
- Default session lifetime: 12 hours
- Changing password signs out all other devices (token version bump)
- Admin-issued passwords are temporary — user must set their own on next login

### Login throttling

- Sliding-window rate limiter per (IP + username)
- After 8 failed attempts in 15 minutes, the account is temporarily locked
- Successful login resets the counter
- Password change has its own throttle

### CSRF protection

- SameSite=Strict cookies prevent cross-site cookie sending
- Additionally, all mutating API calls require the `X-Requested-With: fetch` header, which cross-site forms cannot set

### Security headers

Every response includes:
- `Content-Security-Policy`: strict policy allowing only self, cdnjs, and Google Fonts
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `X-Frame-Options: DENY`
- `Permissions-Policy: geolocation=(), camera=(), microphone=()`
- `Strict-Transport-Security` (when `COOKIE_SECURE=true`)

### API responses

- All `/api/` responses include `Cache-Control: no-store`
- Unauthenticated API requests return `401`
- Non-admin access to admin endpoints returns `403`

---

## 17. CLI Tools

Run from the project directory with:
```bash
python -m app.cli <command> [options]
```

### Commands

| Command | Description |
|---------|-------------|
| `init-db` | Create all database tables (also happens on server start) |
| `create-admin <username>` | Create or update an admin account. Options: `--password`, `--display-name` |
| `import-users <csv>` | Bulk import users from CSV. Option: `--replace` (replace party names instead of adding) |
| `reset-password <username>` | Reset a user's password. Option: `--password` (specific password, otherwise generated) |
| `disable-user <username>` | Disable a user account (signs them out) |
| `enable-user <username>` | Re-enable a user account |
| `unassigned` | List upstream party names that no user tracks |
| `template <output.csv>` | Generate a starter CSV with every upstream party name |

### Bulk import CSV format

Columns: `username, party_names, display_name, company, email, phone, role, password`

- `party_names`: pipe-separated (e.g., `JSW STEEL LIMITED|JSW STEEL LTD`)
- `role`: `party` (default) or `admin`
- `password`: blank = auto-generated and printed once
- Existing users are updated; new users are created

Example (`users.sample.csv`):
```csv
username,party_names,display_name,company,email,phone,role,password
ttp.stores,Ttp Technologies (P) Ltd,Stores desk,TTP Technologies,,,party,
krishna.group,SHREE KRISHNA ISPAT|Ttp Technologies (P) Ltd,Ravi,Krishna Group,,,party,
```

---

## 18. API Reference

All API endpoints require authentication unless noted. Responses are JSON.

### Authentication

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/login` | Sign in. Body: `{username, password}`. Sets session cookie. |
| `POST` | `/api/auth/logout` | Sign out. Deletes session cookie. |
| `GET` | `/api/auth/me` | Current user info, party names, session expiry. |
| `POST` | `/api/auth/change-password` | Change own password. Body: `{current_password, new_password}`. |

### Tracking (party-scoped)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Map settings, refresh interval, GPS stale threshold. |
| `GET` | `/api/shipments` | List shipments. Query: `scope` (active/delivered/all), `q` (search), `party` (filter). Includes KPI counts. |
| `GET` | `/api/shipments/{id}` | Single shipment with full timeline, trail points and position. |
| `GET` | `/api/notifications` | User's notifications (limit: 50-200). |
| `POST` | `/api/notifications/read` | Mark notifications as read. Body: `{ids: [1,2,3]}` or `{}` for all. |
| `GET` | `/api/events` | Server-sent events stream for real-time notifications. |

### Contact / CRM

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/public/contact` | Public (unauthenticated) support contacts for the login page. |
| `GET` | `/api/contact` | Authenticated support contacts. |
| `GET` | `/api/admin/contact` | Admin: full contact data with previews. |
| `POST` | `/api/admin/contact` | Admin: add a new support contact. |
| `PUT` | `/api/admin/contact/{id}` | Admin: update a contact. |
| `DELETE` | `/api/admin/contact/{id}` | Admin: remove a contact. |

### Admin user management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/users` | List all users. Query: `q` (search). |
| `POST` | `/api/admin/users` | Create user. Returns generated password. |
| `PATCH` | `/api/admin/users/{id}` | Update user fields. |
| `DELETE` | `/api/admin/users/{id}` | Delete user. |
| `POST` | `/api/admin/users/{id}/reset-password` | Reset password (generated). |
| `GET` | `/api/admin/party-names` | All upstream party names with counts and assigned users. Query: `q`. |
| `GET` | `/api/admin/audit` | Audit log. Query: `limit` (1-500). |

### Maps proxy

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/olamaps/{path}` | Proxied Ola Maps tile requests. Auth required. API key added server-side. |

### Health check

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Returns 200 when DB answers and both sync loops succeeded recently; 503 otherwise. |

---

## 19. Database

### Engine

- **Default**: SQLite with WAL journaling, stored at `data/tracker.db`
- **Production**: PostgreSQL via `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/tracker`

### Tables

| Table | Purpose |
|-------|---------|
| `users` | User accounts (username, password hash, role, profile, token version) |
| `user_party_names` | Many-to-many: which party names each user tracks |
| `shipments` | All shipments from upstream, with derived status and milestones |
| `vehicle_positions` | Latest GPS position per vehicle (updated every 60s) |
| `track_points` | Breadcrumb trail for route visualisation (retained 30 days) |
| `notifications` | Per-user alerts for status changes |
| `audit_log` | Every admin action recorded |
| `app_settings` | Key-value store for admin-editable settings (e.g., CRM contacts) |
| `sync_state` | Last success/error time for each sync loop |

### Auto-migration

On startup, the app:
1. Creates all missing tables (`Base.metadata.create_all`)
2. Adds any missing columns to existing tables (defined in `db._ADDED_COLUMNS`)

This means the database schema evolves automatically for minor additions. For larger schema changes in production, add Alembic.

### SQLite pragmas

When using SQLite, the app sets:
- `PRAGMA journal_mode=WAL` (concurrent reads)
- `PRAGMA foreign_keys=ON`
- `PRAGMA busy_timeout=5000`

---

## 20. Deployment (Docker)

### Dockerfile

The image uses `python:3.12-slim`, installs dependencies, copies the application, creates a non-root user (`tracker`, uid 10001), and runs uvicorn with one worker.

### docker-compose.yml

```yaml
services:
  tracker:
    build: .
    env_file: .env
    ports:
      - "127.0.0.1:8000:8000"   # put nginx/Caddy with HTTPS in front
    volumes:
      - tracker-data:/srv/data
    restart: unless-stopped
volumes:
  tracker-data:
```

### Building and running

```bash
docker compose up -d --build
```

### Health check

The Docker image includes a built-in health check that hits `/healthz` every 60 seconds.

---

## 21. Production Checklist

- [ ] **HTTPS**: Serve behind nginx or Caddy with TLS. Keep `COOKIE_SECURE=true`.
- [ ] **Proxy headers**: Run uvicorn with `--proxy-headers` only behind your own proxy.
- [ ] **One poller**: The Docker image runs one worker. Scale by adding web-only containers with `RUN_POLLER=false` against Postgres.
- [ ] **Login rate limit**: The in-process throttle is per-process. Add rate limiting on `/api/auth/login` at the proxy level.
- [ ] **SSE through nginx**: Add `proxy_buffering off; proxy_read_timeout 1h;` for `/api/events`.
- [ ] **Ola Maps key**: Set `OLA_MAPS_API_KEY` for the live map. The key never reaches browsers.
- [ ] **Monitor health**: Watch `GET /healthz` — returns 503 when either sync loop hasn't succeeded recently.
- [ ] **Backup**: Back up the SQLite database (the `data/` volume) or configure Postgres backups.
- [ ] **Rotate credentials**: Change the upstream service password if it has been shared outside the server.
- [ ] **Session secret**: Ensure `SESSION_SECRET` is unique per deployment and at least 32 characters.

---

## 22. Monitoring & Health Checks

### `/healthz` endpoint

Returns JSON with the status of both sync loops:

```json
{
  "ok": true,
  "sync": {
    "shipments": {
      "ok_at": "2026-10-24T06:30:00+00:00",
      "fresh": true,
      "last_error": null
    },
    "locations": {
      "ok_at": "2026-10-24T06:30:30+00:00",
      "fresh": true,
      "last_error": null
    }
  }
}
```

- **200**: Both sync loops are healthy
- **503**: One or both sync loops have not succeeded within their threshold (5x the polling interval)

### What to monitor

| Metric | Source | Alert on |
|--------|--------|----------|
| Health check | `GET /healthz` | HTTP 503 |
| Shipment sync | `sync.shipments.fresh` | `false` for >10 minutes |
| GPS sync | `sync.locations.fresh` | `false` for >5 minutes |
| Upstream errors | Server logs (`tracker.sync`) | Repeated sync failures |
| Ola Maps | Server logs (`tracker.maps`) | 401/403 rejections |

---

## 23. Mobile & PWA Support

### Responsive design

The application is fully responsive with breakpoints at:
- **860px**: Layout switches from side-by-side (list + map) to stacked. Map moves below the list.
- **520px**: Login page aside is hidden, larger touch targets, simplified header.

### Progressive Web App

The app includes a `manifest.webmanifest` that allows it to be installed as a home-screen app:

- **App name**: "Where is my load"
- **Short name**: "My load"
- **Display mode**: Standalone (no browser chrome)
- **Theme colour**: #0F1A30 (Balaji Transports navy)
- **Icons**: 192px and 512px PNG versions of the Balaji Transports logo

To install: On Chrome/Safari, tap the browser menu → "Add to Home Screen" / "Install App".

### Touch optimisations

- Minimum 44px touch targets
- `-webkit-tap-highlight-color: transparent` for clean taps
- `env(safe-area-inset-*)` for iPhone notch/safe areas
- Smooth scroll behaviour
- Pull-to-refresh compatible layout

---

## 24. Theming

### Dark theme (default)

Navy blue background (#0A1224) with gold (#C7A84E) accents — the Balaji Transports brand colours.

### Light theme

Light background with the same gold accent. Each user can switch from the account menu (top right → "Light theme" / "Dark theme"). The preference is saved in `localStorage` and restored on next visit.

### Map theme

The map automatically switches between Ola Maps light and dark styles when the user toggles the theme.

### Brand assets

| File | Purpose | Size |
|------|---------|------|
| `static/logo-512.png` | Full Balaji Transports seal (login page, PWA icon) | 512x512 |
| `static/logo-192.png` | PWA icon | 192x192 |
| `static/mark-96.png` | BT monogram (header) | 96x96 |
| `static/mark-256.png` | BT monogram (large) | 256x256 |
| `static/favicon-32.png` | Browser favicon | 32x32 |
| `static/favicon-48.png` | Browser favicon | 48x48 |
| `static/apple-touch-icon.png` | iOS home screen icon | standard |

To rebrand, replace these files with the same names and sizes.

---

## 25. Troubleshooting

### "command not found: uvicorn"

Dependencies aren't installed, or the virtual environment isn't activated.

```bash
pip3 install -r requirements.txt
# Or use the full path:
.venv/bin/uvicorn app.main:app --port 8000
```

### "Address already in use" (port 8000)

A previous server process is still running.

```bash
lsof -ti:8000 | xargs kill -9
```

### "unsupported operand type(s) for |: 'type' and 'NoneType'"

You're running Python 3.9, which doesn't support the `X | None` syntax at runtime. The codebase has been updated to use `Optional[X]` for all SQLAlchemy and Pydantic fields. If you see this error, ensure you have the latest version of the code.

### Sign-in fails silently (no error, page refreshes)

`COOKIE_SECURE=true` is set but you're accessing over HTTP. Set `COOKIE_SECURE=false` in `.env` for local testing.

### "Map unavailable" message

The `OLA_MAPS_API_KEY` is empty or invalid. Set it in `.env`. Everything except the map continues to work.

### "Too many attempts. Wait 15 minutes and try again."

Login throttling has kicked in after 8 failed attempts. Wait 15 minutes or restart the server to reset the in-memory counter.

### Notifications not appearing

- Admins don't receive notifications (by design)
- The first database sync is silent to avoid flooding
- Check that the SSE connection is active (browser dev tools → Network → EventStream)
- Ensure the user has the correct party names assigned

### WhatsApp messages not sending

- Check `WHATSAPP_ENABLED=true` in `.env`
- Ensure the user has a valid phone number and WhatsApp alerts enabled
- Check server logs for `tracker.sync` errors
- The upstream WhatsApp API must be reachable

### Shipments not updating

- Check `/healthz` — if the sync loop is failing, the error will be shown
- Check server logs for `tracker.sync` errors
- Verify upstream credentials are correct in `.env`
- Ensure `RUN_POLLER=true` on exactly one process

---

## 26. Project File Structure

```
shipment-tracker/
├── app/                          # Python backend
│   ├── __init__.py
│   ├── main.py                   # FastAPI app, middleware, routes, lifespan
│   ├── config.py                 # Settings from .env (Pydantic BaseSettings)
│   ├── db.py                     # SQLAlchemy engine, session, auto-migration
│   ├── models.py                 # ORM models (User, Shipment, Notification, etc.)
│   ├── auth.py                   # Authentication: login, logout, sessions, throttling
│   ├── api.py                    # Party-facing API: shipments, notifications, SSE
│   ├── admin.py                  # Admin API: user CRUD, party names, audit log
│   ├── contact.py                # CRM contact management (multi-contact support)
│   ├── domain.py                 # Business rules: status derivation, normalisation, GPS
│   ├── sync.py                   # Background poller: shipments + GPS + notifications
│   ├── upstream.py               # HTTP client for external.balajitransports.in
│   ├── maps.py                   # Ola Maps tile proxy with LRU cache
│   └── cli.py                    # CLI commands: create-admin, import-users, etc.
├── static/                       # Frontend (served as static files)
│   ├── index.html                # Main tracking page
│   ├── admin.html                # Admin console
│   ├── login.html                # Login page
│   ├── app.js                    # Tracking page logic (ES module)
│   ├── admin.js                  # Admin console logic (ES module)
│   ├── login.js                  # Login page logic (ES module)
│   ├── common.js                 # Shared helpers, header, CRM, password dialog
│   ├── theme.js                  # Theme initialisation (runs before page paint)
│   ├── app.css                   # All styles (dark-first, responsive)
│   ├── manifest.webmanifest      # PWA manifest
│   └── *.png                     # Brand assets (logos, favicons)
├── scripts/
│   └── ensure_env.py             # Pre-start: generate SESSION_SECRET, check credentials
├── tests/
│   └── test_domain.py            # Domain logic unit tests
├── data/
│   └── tracker.db                # SQLite database (created on first run)
├── .env                          # Runtime configuration (not committed)
├── .env.example                  # Template for .env
├── requirements.txt              # Python dependencies
├── requirements-dev.txt          # Dev dependencies (pytest, etc.)
├── Dockerfile                    # Production container image
├── docker-compose.yml            # Single-command deployment
├── run.sh                        # One-click start (Linux/macOS)
├── run.bat                       # One-click start (Windows)
├── users.sample.csv              # Example bulk import CSV
├── .gitignore                    # Git ignore rules
├── .dockerignore                 # Files excluded from Docker build context
├── PRODUCT_DOCUMENTATION.md      # This document — full product reference
└── README.md                     # Quick-start developer guide
```

---

*This document covers the complete "Where is my load" shipment tracking platform by Balaji Transports. For developer quick-start notes, see `README.md`. For questions or support, contact the Balaji Transports technology team.*
