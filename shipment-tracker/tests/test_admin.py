"""Admin API integration tests."""
from __future__ import annotations

import pytest
from .conftest import login


@pytest.mark.asyncio
async def test_admin_list_users(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.get("/api/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) >= 2
    assert "has_more" in body
    names = {u["username"] for u in body["items"]}
    assert "admin" in names and "party1" in names


@pytest.mark.asyncio
async def test_admin_list_users_pagination(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.get("/api/admin/users?limit=1&offset=0")
    body = r.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_party_cannot_list_users(client, seed_users):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/admin/users")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_user(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.post("/api/admin/users",
                          json={"username": "newuser", "display_name": "New User",
                                "company": "New Co", "role": "party", "party_names": ["ACME CORP"]},
                          headers={"x-requested-with": "fetch"})
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["username"] == "newuser"
    assert "password" in body
    assert body["user"]["party_names"] == ["ACME CORP"]


@pytest.mark.asyncio
async def test_create_user_duplicate(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.post("/api/admin/users",
                          json={"username": "admin", "display_name": "Dup",
                                "company": "", "role": "admin", "party_names": []},
                          headers={"x-requested-with": "fetch"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_update_user(client, seed_users):
    uid = seed_users["party"].id
    await login(client, "admin", "AdminPass!123")
    r = await client.patch(f"/api/admin/users/{uid}",
                           json={"display_name": "Updated Name", "company": "Updated Co",
                                 "role": "party", "active": True, "party_names": ["NEW PARTY"]},
                           headers={"x-requested-with": "fetch"})
    assert r.status_code == 200
    assert r.json()["user"]["display_name"] == "Updated Name"
    assert r.json()["user"]["party_names"] == ["NEW PARTY"]


@pytest.mark.asyncio
async def test_delete_user(client, seed_users):
    uid = seed_users["party"].id
    await login(client, "admin", "AdminPass!123")
    r = await client.delete(f"/api/admin/users/{uid}",
                            headers={"x-requested-with": "fetch"})
    assert r.status_code == 204

    r2 = await client.get("/api/admin/users")
    assert uid not in [u["id"] for u in r2.json()["items"]]


@pytest.mark.asyncio
async def test_audit_log(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    await client.post("/api/admin/users",
                      json={"username": "auditme", "display_name": "Audit",
                            "company": "", "role": "party", "party_names": []},
                      headers={"x-requested-with": "fetch"})
    r = await client.get("/api/admin/audit")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) >= 1
    assert any(a["action"] == "user.create" for a in body["items"])


@pytest.mark.asyncio
async def test_audit_pagination(client, seed_users):
    await login(client, "admin", "AdminPass!123")
    r = await client.get("/api/admin/audit?limit=1")
    body = r.json()
    assert len(body["items"]) <= 1
    assert "has_more" in body
