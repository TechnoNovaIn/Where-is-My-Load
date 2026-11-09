"""Shipment API integration tests."""
from __future__ import annotations

import pytest
from .conftest import login


@pytest.mark.asyncio
async def test_shipments_unauthenticated(client, seed_shipments):
    r = await client.get("/api/shipments")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_shipments_active(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments?scope=active")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert all(s["status"] != "delivered" for s in body["items"])
    assert "has_more" in body


@pytest.mark.asyncio
async def test_shipments_delivered(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments?scope=delivered")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert all(s["status"] == "delivered" for s in body["items"])


@pytest.mark.asyncio
async def test_shipments_pagination(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments?scope=active&limit=2&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True

    r2 = await client.get("/api/shipments?scope=active&limit=2&offset=2")
    body2 = r2.json()
    assert len(body2["items"]) == 1
    assert body2["has_more"] is False


@pytest.mark.asyncio
async def test_shipments_search(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments?scope=active&q=0001")
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["vehicle_no"] == "KA 01 AB 0001"


@pytest.mark.asyncio
async def test_shipment_detail(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments/1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert "timeline" in body


@pytest.mark.asyncio
async def test_shipment_not_found(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments/9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_admin_sees_all(client, seed_shipments):
    await login(client, "admin", "AdminPass!123")
    r = await client.get("/api/shipments?scope=active")
    body = r.json()
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_kpi_counts(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments?scope=active")
    body = r.json()
    assert body["counts"]["active"] == 3
    assert body["counts"]["delivered"] == 2


@pytest.mark.asyncio
async def test_csv_export(client, seed_shipments):
    await login(client, "party1", "PartyPass!123")
    r = await client.get("/api/shipments/export.csv?scope=active")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    lines = r.text.strip().split("\n")
    assert len(lines) == 4  # header + 3 active
    assert lines[0].startswith("ID,")
