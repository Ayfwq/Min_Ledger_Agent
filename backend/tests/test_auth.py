from __future__ import annotations

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_optional_password_protects_api(client, monkeypatch):
    monkeypatch.setattr(settings, "app_password", "s3cret")

    resp = await client.get("/api/v1/inputs")
    assert resp.status_code == 401

    resp = await client.get("/api/v1/inputs", headers={"X-App-Password": "s3cret"})
    assert resp.status_code == 200

    resp = await client.post("/api/v1/auth/verify", json={"password": "wrong"})
    assert resp.status_code == 401

    resp = await client.post("/api/v1/auth/verify", json={"password": "s3cret"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # public endpoints stay open
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
