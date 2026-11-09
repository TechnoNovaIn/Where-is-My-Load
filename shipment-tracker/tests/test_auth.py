"""Auth flow integration tests."""
from __future__ import annotations

import pytest
from .conftest import login


@pytest.mark.asyncio
async def test_login_success(client, seed_users):
    r = await login(client, "admin", "AdminPass!123")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "admin"
    assert "bt_session" in r.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(client, seed_users):
    r = await login(client, "admin", "WrongPassword!1")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user(client, seed_users):
    r = await login(client, "nobody", "WrongPassword!1")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_unauthenticated(client, seed_users):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client, seed_users):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "party1"
    assert body["party_names"] == ["TEST PARTY"]


@pytest.mark.asyncio
async def test_logout(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.post("/api/auth/logout", headers={"x-requested-with": "fetch"})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_change_password(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.post("/api/auth/change-password",
                          json={"current_password": "AdminPass!123", "new_password": "BrandNew!Pass456"},
                          headers={"x-requested-with": "fetch"})
    assert r.status_code == 200
    r2 = await login(client, "admin", "BrandNew!Pass456")
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.post("/api/auth/change-password",
                          json={"current_password": "WrongCurrent!1", "new_password": "BrandNew!Pass456"},
                          headers={"x-requested-with": "fetch"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_csrf_protection(client, seed_users):
    r = await client.post("/api/auth/login",
                          json={"username": "admin", "password": "AdminPass!123"})
    assert r.status_code == 403
