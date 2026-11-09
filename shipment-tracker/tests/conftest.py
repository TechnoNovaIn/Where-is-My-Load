"""Shared fixtures for integration tests."""
from __future__ import annotations

import os

os.environ.update({
    "UPSTREAM_USERNAME": "test",
    "UPSTREAM_PASSWORD": "test",
    "SESSION_SECRET": "a" * 32,
    "DATABASE_URL": "sqlite+aiosqlite://",
    "RUN_POLLER": "false",
    "COOKIE_SECURE": "false",
    "OLA_MAPS_API_KEY": "",
})

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import engine, SessionLocal, utcnow
from app.auth import hash_password
from app.models import Base, User, UserPartyName, Shipment


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def _reset_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def seed_users(db):
    now = utcnow()
    admin = User(username="admin", display_name="Admin", company="Balaji",
                 role="admin", password_hash=hash_password("AdminPass!123"),
                 active=True, created_at=now, updated_at=now)
    party = User(username="party1", display_name="Party User", company="Test Co",
                 role="party", password_hash=hash_password("PartyPass!123"),
                 active=True, created_at=now, updated_at=now)
    db.add_all([admin, party])
    await db.commit()
    await db.refresh(admin)
    await db.refresh(party)
    pn = UserPartyName(user_id=party.id, party_name="TEST PARTY", party_key="testparty")
    db.add(pn)
    await db.commit()
    return {"admin": admin, "party": party}


@pytest_asyncio.fixture
async def seed_shipments(db, seed_users):
    now = utcnow()
    shipments = []
    for i in range(1, 6):
        sh = Shipment(id=i, party_name_raw="TEST PARTY", party_key="testparty",
                      vehicle_id=100 + i, vehicle_no=f"KA 01 AB {i:04d}",
                      product="Steel Coil", net_weight=20.0,
                      origin="Toranagallu", destination="Bangalore",
                      status="in_transit" if i <= 3 else "delivered",
                      status_at=now, first_seen_at=now, updated_at=now)
        shipments.append(sh)
    db.add_all(shipments)
    await db.commit()
    return shipments


@pytest_asyncio.fixture
async def client():
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def login(client: AsyncClient, username: str, password: str) -> AsyncClient:
    r = await client.post("/api/auth/login",
                          json={"username": username, "password": password},
                          headers={"x-requested-with": "fetch"})
    if r.status_code == 200:
        client.cookies.set("bt_session", r.cookies.get("bt_session"))
    return r
