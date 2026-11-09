# Where is my load

Live load tracking for Balaji Transports customers.

Customers (parties) sign in and see only the loads for their party names: live truck
position, route trail, driver phone, a progress timeline, and alerts as the status changes.
Balaji Transports staff (admins) see every shipment and manage logins in the user master.
Dark theme by default in the Balaji Transports navy and gold; each user can switch to light from
the account menu. On phones it can be added to the home screen as "Where is my load".

Brand assets live in `static/`: `logo-512.png` / `logo-192.png` (full seal, used on the sign-in
page and as the app icon), `mark-*.png` and `favicon-*.png` (the BT monogram, legible at small
sizes). To change the logo, replace those files with the same names and sizes.
Once a load is delivered, live location and driver contact are withdrawn; the shipment stays
visible under **Delivered** for 90 days.

```
browser ──cookie session──▶ FastAPI (this app) ──service JWT──▶ external.balajitransports.in
                              │  poller: shipments every 120 s, GPS every 60 s
                              └─ SQLite / Postgres: users + party names, shipments, positions, alerts, audit
```

The upstream credentials never reach the browser. Parties authenticate against this app.

## Quick start

**Windows:** double-click `run.bat` (or run it from a terminal). **Linux/macOS:** `./run.sh`.
The first run creates `.env` from `.env.example` and stops; fill in `UPSTREAM_USERNAME`,
`UPSTREAM_PASSWORD` and `SESSION_SECRET`, and set `COOKIE_SECURE=false` while you test over
plain `http://`. Run the script again: it installs dependencies and starts the server on port 8000.

Create the first administrator (in a second terminal, from the project folder):

```bash
.venv/bin/python -m app.cli create-admin ops.admin --password "choose-a-strong-one"   # Linux/macOS
.venv\Scripts\python -m app.cli create-admin ops.admin --password "choose-a-strong-one" # Windows
```

Open http://localhost:8000, sign in as the admin, and go to **Users**.

## User master

Each login carries its own list of **party names** (the exact `PartyName` text from the
shipments API). A party user sees every shipment whose `PartyName` matches any name on their
list; matching ignores case, spaces and punctuation. One login can cover several party names
(group companies, spelling variants), and one party name can be on several logins.

Roles:

| Role | Sees | Can |
|---|---|---|
| `party` | shipments for their party names, driver phone while live, notifications | track |
| `admin` | all shipments (with party name on every row) | track, manage the user master |

The **Users** console (`/admin`) has three tabs:

- **Users**: create, edit, disable, delete, reset password. New passwords are generated and
  shown once in a copyable dialog. Disabling, role changes and resets sign the user out
  everywhere immediately.
- **Party names**: every `PartyName` seen in shipments with counts and the logins that track it.
  Filter to names without a login and create one in a click.
- **Activity**: audit log of every change to the user master (who, what, when).

Removing a party name from a user also removes their old alerts for those shipments.

### Customer care contact

Admins set the customer-care (CRM) number under **Users → Customer care**: label, phone, optional
alternate number, email, hours and a WhatsApp switch. Party users then see it:

- in the header on every page (a gold call button with the number; tap to call on phones),
- on every shipment, with "quote shipment #…" so follow-ups reference the right load,
- on the sign-in page, for forgotten passwords.

Accepted numbers: 10-digit mobiles, landlines with STD code, and 1800 toll-free numbers. Clear the
phone number to hide the contact everywhere. Changes are recorded in the Activity tab.

Driver names are not shown to parties; only the driver's phone number while the load is live.

### Passwords

Every user can change their password from the account menu (top right) with **Change password**.
It needs the current password; other devices are signed out, the current one stays signed in.
Passwords must be at least 10 characters and must not contain the username.

Passwords issued by an admin (new user, reset) are temporary: at the next sign-in the user must
set their own before they can use the site.

### Bulk import

```bash
python -m app.cli template users.csv          # starter CSV with every upstream party name
python -m app.cli import-users users.csv      # add/update users; add party names
python -m app.cli import-users users.csv --replace   # party names become exactly the CSV list
```

Columns: `username, party_names, display_name, company, email, phone, role, password`.
`party_names` is `|`-separated. Blank password = generated and printed once. See `users.sample.csv`.

Other commands: `reset-password`, `disable-user`, `enable-user`, `unassigned` (party names no
login tracks).

## Status rules

| Party sees | Upstream evidence |
|---|---|
| Truck assigned | `DOAllocatedDate` |
| Loading at plant | `PlantEntrydate` |
| Dispatched | `PlantExitDate` or `JSWLeft` |
| In transit | `TMKEntry` / `TMKLeft` (Tumkur checkpoint) |
| Near destination | `BLREntry`; for Tumkur deliveries, `TMKEntry` |
| At unloading point | `unloadLocReachedTime` |
| Delivered | `unloadedTime`, **or** any return-leg stamp (`BLRLeft`, `TMKReEntry`, …), **or** the same truck was assigned a newer load |

The last two delivery rules exist because the feed often omits `unloadedTime`. They are shown
to the party as "Confirmed when the truck left your site". Statuses never move backwards.

GPS: positions with null coordinates, coordinates outside India, or the `1970-01-01T05:30`
placeholder timestamp are discarded. Fixes older than `GPS_STALE_MINUTES` are drawn faded
and labelled as a weak signal. Driver numbers that are placeholders (`1234567890`, `000`, …)
show as "not on record".

## Notifications

Each status advance writes a notification for every active party user whose list includes that
party name (admins don't get alerts). The browser receives it over
server-sent events (`/api/events`) within ~5 s: the bell count updates, a toast appears, and
if the user allowed it, a system notification shows while the tab is in the background.
The first sync on an empty database is silent so parties are not flooded with history.

## Production checklist

- Serve over HTTPS behind nginx/Caddy; keep `COOKIE_SECURE=true`. Run uvicorn with
  `--proxy-headers` only behind your own proxy.
- **Exactly one poller.** The Docker image runs one worker. To scale, use Postgres and add
  web-only containers with `RUN_POLLER=false`. The login throttle is per process, so also
  rate-limit `/api/auth/login` at the proxy.
- For SSE through nginx: `proxy_buffering off; proxy_read_timeout 1h;` on `/api/events`.
- Maps are **Ola Maps** vector tiles rendered with MapLibre. Put the key in `OLA_MAPS_API_KEY`;
  it never reaches the browser, because tiles load through `/olamaps/...` on this server
  (signed-in users only, with a 64 MB in-memory cache to save Ola quota). If the key is missing
  or rejected, the map panel says so and everything else keeps working.
  production traffic. The CSP picks up the tile host automatically.
- Monitor `GET /healthz` (503 when either sync loop has not succeeded recently).
- Back up the database (SQLite: the `data/` volume).
- Tables are created on startup. Add Alembic before changing the schema in production.
- Rotate the upstream service password if it has been shared outside the server.

## Development

```bash
pytest -q
```

Upstream quirk handled in `app/upstream.py`: when the request's `Accept` is strictly
`application/json`, the API returns the JSON payload serialised twice (a JSON string); the
client unwraps it.
