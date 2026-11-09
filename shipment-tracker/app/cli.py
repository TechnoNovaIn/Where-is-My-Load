"""Admin commands. Usage: python -m app.cli <command> --help

Day-to-day user management happens in the web console at /admin. The CLI is for the first
admin account, bulk imports and break-glass resets.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys

from sqlalchemy import func, select

from .admin import USERNAME_RE, _clean_names, generate_password
from .auth import hash_password
from .db import SessionLocal, init_db, utcnow
from .models import Shipment, User, UserPartyName


async def _upsert_user(db, username: str, *, role: str, display_name: str = "", company: str = "",
                       email: str = "", phone: str = "", password: str | None = None,
                       party_names: list[str] | None = None, replace_names: bool = False) -> tuple[User, str | None]:
    username = username.strip().casefold()
    if not USERNAME_RE.match(username):
        raise ValueError(f"invalid username '{username}'")
    if role not in ("party", "admin"):
        raise ValueError(f"role must be 'party' or 'admin', got '{role}'")
    user = await db.scalar(select(User).where(User.username == username))
    issued = None
    now = utcnow()
    if user is None:
        issued = password or generate_password()
        user = User(username=username, role=role, password_hash=hash_password(issued),
                    must_change_password=password is None and role == "party",
                    created_at=now, updated_at=now, party_names=[])
        db.add(user)
    elif password:
        user.password_hash, user.token_version, issued = hash_password(password), user.token_version + 1, password
    for field, value in (("display_name", display_name), ("company", company), ("email", email), ("phone", phone)):
        if value:
            setattr(user, field, value.strip())
    user.role = role
    if party_names is not None:
        wanted = _clean_names(party_names)
        wanted_keys = {k for _, k in wanted}
        current = {p.party_key: p for p in user.party_names}
        keep = [p for k, p in current.items() if k in wanted_keys] if replace_names else list(current.values())
        user.party_names = keep + [UserPartyName(party_name=n, party_key=k) for n, k in wanted if k not in current]
    user.updated_at = now
    return user, issued


async def cmd_create_admin(a) -> None:
    await init_db()
    async with SessionLocal() as db:
        user, pw = await _upsert_user(db, a.username, role="admin", display_name=a.display_name or "",
                                      company="Balaji Transports", password=a.password)
        await db.commit()
    print(f"admin '{user.username}' ready" + (f"; password: {pw}" if pw else ""))


async def cmd_import_users(a) -> None:
    """CSV columns: username,party_names,display_name,company,email,phone,role,password
    party_names: exact PartyName texts separated by '|'. role: party (default) or admin.
    Existing users are updated; with --replace their party names become exactly the CSV list,
    otherwise names are added. Blank password -> generated for new users, printed once."""
    await init_db()
    issued: list[tuple[str, str]] = []
    async with SessionLocal() as db:
        with open(a.csv, newline="", encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f), start=2):
                try:
                    user, pw = await _upsert_user(
                        db, row.get("username") or "", role=(row.get("role") or "party").strip() or "party",
                        display_name=row.get("display_name") or "", company=row.get("company") or "",
                        email=row.get("email") or "", phone=row.get("phone") or "",
                        password=(row.get("password") or "").strip() or None,
                        party_names=[n for n in (row.get("party_names") or "").split("|") if n.strip()],
                        replace_names=a.replace,
                    )
                    await db.flush()
                    if pw:
                        issued.append((user.username, pw))
                except ValueError as e:
                    print(f"line {i}: {e}; skipped", file=sys.stderr)
        await db.commit()
    print("import complete")
    if issued:
        print("\nCredentials (shown once):")
        for u, pw in issued:
            print(f"  {u:<28} {pw}")


async def cmd_reset_password(a) -> None:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == a.username.casefold()))
        if not user:
            sys.exit("no such user")
        pw = a.password or generate_password()
        user.password_hash, user.token_version = hash_password(pw), user.token_version + 1
        user.must_change_password = not a.password  # generated -> user must pick their own
        await db.commit()
    print(f"password reset (existing sessions signed out): {pw}")


async def cmd_set_active(a) -> None:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.username == a.username.casefold()))
        if not user:
            sys.exit("no such user")
        user.active, user.token_version = a.active, user.token_version + 1
        await db.commit()
    print("updated")


async def cmd_unassigned(a) -> None:
    """Upstream party names that no user tracks yet."""
    async with SessionLocal() as db:
        tracked = select(UserPartyName.party_key)
        rows = (await db.execute(
            select(func.max(Shipment.party_name_raw), func.count(), func.max(Shipment.shipment_date))
            .where(Shipment.party_key.not_in(tracked), Shipment.party_key != "")
            .group_by(Shipment.party_key).order_by(func.count().desc())
        )).all()
    if not rows:
        print("every party name is assigned to at least one user")
    for name, n, last in rows:
        print(f"{n:>5}  {last}  {name}")


async def cmd_template(a) -> None:
    """Write a starter import CSV listing every party name seen upstream."""
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(func.max(Shipment.party_name_raw), func.count()).where(Shipment.party_key != "")
            .group_by(Shipment.party_key).order_by(func.count().desc())
        )).all()
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "party_names", "display_name", "company", "email", "phone", "role", "password"])
        for name, _ in rows:
            w.writerow(["", name, "", name, "", "", "party", ""])
    print(f"wrote {len(rows)} rows to {a.out}; fill usernames, merge rows that belong to one login")


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-db"); s.set_defaults(fn=lambda a: init_db())
    s = sub.add_parser("create-admin", help="create or update a Balaji Transports admin login")
    s.add_argument("username"); s.add_argument("--password"); s.add_argument("--display-name"); s.set_defaults(fn=cmd_create_admin)
    s = sub.add_parser("import-users", help=cmd_import_users.__doc__)
    s.add_argument("csv"); s.add_argument("--replace", action="store_true"); s.set_defaults(fn=cmd_import_users)
    s = sub.add_parser("reset-password"); s.add_argument("username"); s.add_argument("--password"); s.set_defaults(fn=cmd_reset_password)
    s = sub.add_parser("disable-user"); s.add_argument("username"); s.set_defaults(fn=cmd_set_active, active=False)
    s = sub.add_parser("enable-user"); s.add_argument("username"); s.set_defaults(fn=cmd_set_active, active=True)
    s = sub.add_parser("unassigned", help=cmd_unassigned.__doc__); s.set_defaults(fn=cmd_unassigned)
    s = sub.add_parser("template", help=cmd_template.__doc__); s.add_argument("out"); s.set_defaults(fn=cmd_template)

    args = p.parse_args()
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
