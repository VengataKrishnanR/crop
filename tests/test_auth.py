"""AUTH_MODE=apikey — the shared-secret gate on /api/*."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.api


@pytest.fixture
def locked(client: TestClient, monkeypatch) -> TestClient:
    import server.app as server_app

    monkeypatch.setattr(
        server_app, "settings",
        dataclasses.replace(server_app.settings, auth_mode="apikey", api_key="s3cret"),
    )
    return client


def test_health_stays_open(locked: TestClient) -> None:
    assert locked.get("/api/health").status_code == 200


def test_api_requires_the_key(locked: TestClient) -> None:
    assert locked.get("/api/cases").status_code == 401
    assert locked.get("/api/cases", headers={"X-API-Key": "wrong"}).status_code == 401
    assert locked.get("/api/cases", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert locked.get("/api/cases", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_ui_assets_stay_open(locked: TestClient) -> None:
    assert locked.get("/").status_code == 200
