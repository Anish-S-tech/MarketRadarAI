import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def client(database):
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _register(client, org: str) -> dict:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "org_name": org,
            "full_name": "Admin",
            "email": f"{uuid.uuid4().hex[:8]}@{org.lower()}.example.com",
            "password": "correct-horse-battery",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_auth_flow_and_tenant_isolation(client):
    a = await _register(client, "AlphaCo")
    b = await _register(client, "BetaCo")
    ha = {"Authorization": f"Bearer {a['access_token']}"}
    hb = {"Authorization": f"Bearer {b['access_token']}"}

    assert (await client.get("/api/v1/auth/me", headers=ha)).json()["role"] == "admin"
    assert (await client.get("/api/v1/competitors")).status_code == 401

    r = await client.post(
        "/api/v1/competitors", headers=ha, json={"name": "Rival", "domain": "https://rival.com/"}
    )
    assert r.status_code == 201 and r.json()["domain"] == "rival.com"
    cid = r.json()["id"]

    # Tenant B cannot see or fetch tenant A's competitor.
    assert (await client.get("/api/v1/competitors", headers=hb)).json() == []
    assert (await client.get(f"/api/v1/competitors/{cid}", headers=hb)).status_code == 404

    # Refresh rotation: an old refresh token cannot be reused.
    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]})
    assert r2.status_code == 401


async def test_rbac_and_validation(client):
    a = await _register(client, "GammaCo")
    h = {"Authorization": f"Bearer {a['access_token']}"}
    r = await client.post(
        "/api/v1/users",
        headers=h,
        json={
            "email": f"s{uuid.uuid4().hex[:6]}@gamma.example.com",
            "role": "sales",
            "password": "sales-password-123",
        },
    )
    assert r.status_code == 201
    login = await client.post(
        "/api/v1/auth/login", json={"email": r.json()["email"], "password": "sales-password-123"}
    )
    hs = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # sales can read but not create competitors or users
    assert (await client.get("/api/v1/competitors", headers=hs)).status_code == 200
    assert (
        await client.post("/api/v1/competitors", headers=hs, json={"name": "X", "domain": "x.com"})
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/users",
            headers=hs,
            json={"email": "z@z.example.com", "role": "admin", "password": "whatever-123456"},
        )
    ).status_code == 403

    comp = (await client.post("/api/v1/competitors", headers=h, json={"name": "Y", "domain": "y.com"})).json()
    bad = await client.post(
        "/api/v1/sources",
        headers=h,
        json={
            "competitor_id": comp["id"],
            "name": "s",
            "source_type": "webpage",
            "url": "file:///etc/passwd",
        },
    )
    assert bad.status_code == 422
    news = await client.post(
        "/api/v1/sources",
        headers=h,
        json={
            "competitor_id": comp["id"],
            "name": "News",
            "source_type": "news",
            "config": {"query": "Y Corp"},
        },
    )
    assert news.status_code == 201 and news.json()["url"].startswith(
        "https://api.gdeltproject.org/api/v2/doc/doc?"
    )


async def test_api_key_auth(client):
    a = await _register(client, "DeltaCo")
    h = {"Authorization": f"Bearer {a['access_token']}"}
    key = (await client.post("/api/v1/api-keys", headers=h, json={"name": "ci", "role": "executive"})).json()[
        "key"
    ]
    assert (await client.get("/api/v1/events", headers={"Authorization": f"Bearer {key}"})).status_code == 200
    assert (
        await client.get("/api/v1/events", headers={"Authorization": "Bearer mr_bad_key"})
    ).status_code == 401
