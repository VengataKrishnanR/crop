"""AUTH_MODE=users — sign-in, the admin panel, and role-based access."""
from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from conftest import FULL_M2C

pytestmark = pytest.mark.api

ADMIN_EMAIL, ADMIN_PASSWORD = "admin@ccre.local", "ChangeMe123!"


@pytest.fixture
def secured(client: TestClient, monkeypatch) -> TestClient:
    """The same app, with sign-in enforced and the default admin created."""
    import server.app as server_app
    from server.app import app
    from tools.core.db import get_session
    from tools.core.security import ensure_default_admin

    monkeypatch.setattr(server_app, "settings", dataclasses.replace(server_app.settings, auth_mode="users"))
    session = next(app.dependency_overrides[get_session]())
    ensure_default_admin(session)
    session.commit()
    return client


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _make_user(client: TestClient, admin: dict, email: str, role: str, countries=None) -> dict[str, str]:
    resp = client.post("/api/admin/users", headers=admin, json={
        "email": email, "name": email.split("@")[0], "role": role, "password": "Password123",
        "countries": countries or []})
    assert resp.status_code == 201, resp.text
    return _login(client, email, "Password123")


def test_health_and_ui_stay_open(secured: TestClient) -> None:
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/").status_code == 200


def test_everything_else_needs_sign_in(secured: TestClient) -> None:
    for path in ("/api/onboardings", "/api/cases", "/api/kpis", "/api/admin/users", "/api/agents"):
        assert secured.get(path).status_code == 401, path
    bad = secured.get("/api/onboardings", headers={"Authorization": "Bearer forged.token"})
    assert bad.status_code == 401


def test_wrong_password_is_refused(secured: TestClient) -> None:
    resp = secured.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "nope"})
    assert resp.status_code == 401


def test_admin_manages_users_and_roles(secured: TestClient) -> None:
    admin = _login(secured, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert secured.get("/api/auth/me", headers=admin).json()["role"] == "ADMIN"
    _make_user(secured, admin, "pm@dhl.test", "PM")
    users = {u["email"]: u for u in secured.get("/api/admin/users", headers=admin).json()}
    assert users["pm@dhl.test"]["role"] == "PM"

    # Business users need countries
    refused = secured.post("/api/admin/users", headers=admin, json={
        "email": "b@dhl.test", "name": "b", "role": "BUSINESS", "password": "Password123"})
    assert refused.status_code == 400
    # Duplicate emails are refused
    dup = secured.post("/api/admin/users", headers=admin, json={
        "email": "pm@dhl.test", "name": "x", "role": "PM", "password": "Password123"})
    assert dup.status_code == 400

    pm_id = users["pm@dhl.test"]["id"]
    promoted = secured.patch(f"/api/admin/users/{pm_id}", headers=admin, json={"role": "CCRE_TEAM"})
    assert promoted.json()["role"] == "CCRE_TEAM"
    disabled = secured.patch(f"/api/admin/users/{pm_id}", headers=admin, json={"active": False})
    assert disabled.json()["active"] is False
    login = secured.post("/api/auth/login", json={"email": "pm@dhl.test", "password": "Password123"})
    assert login.status_code == 401


def test_last_admin_cannot_be_removed(secured: TestClient) -> None:
    admin = _login(secured, ADMIN_EMAIL, ADMIN_PASSWORD)
    me = next(u for u in secured.get("/api/admin/users", headers=admin).json() if u["email"] == ADMIN_EMAIL)
    assert secured.patch(f"/api/admin/users/{me['id']}", headers=admin,
                         json={"role": "PM"}).status_code == 409
    assert secured.patch(f"/api/admin/users/{me['id']}", headers=admin,
                         json={"active": False}).status_code == 409


def test_only_admin_reaches_the_admin_panel(secured: TestClient) -> None:
    admin = _login(secured, ADMIN_EMAIL, ADMIN_PASSWORD)
    team = _make_user(secured, admin, "team@dhl.test", "CCRE_TEAM")
    assert secured.get("/api/admin/users", headers=team).status_code == 403


def test_business_users_see_only_their_countries_and_business_views(secured: TestClient) -> None:
    admin = _login(secured, ADMIN_EMAIL, ADMIN_PASSWORD)
    team = _make_user(secured, admin, "team@dhl.test", "CCRE_TEAM")
    biz = _make_user(secured, admin, "bg@dhl.test", "BUSINESS", ["bg"])

    mine = secured.post("/api/onboardings", json={"ctry_cd": "BG", "title": "BG"}, headers=biz)
    assert mine.status_code == 201
    other = secured.post("/api/onboardings", json={"ctry_cd": "DE", "title": "DE"}, headers=team)
    assert other.status_code == 201

    visible = [c["country"] for c in secured.get("/api/onboardings", headers=biz).json()]
    assert visible == ["BG"]
    assert secured.get(f"/api/onboardings/{other.json()['id']}", headers=biz).status_code == 404
    assert secured.post("/api/onboardings", json={"ctry_cd": "DE", "title": "x"}, headers=biz).status_code == 403

    # The business front is limited: no internal domain API, KPIs or expert chat.
    for path in ("/api/cases", "/api/rule-sets", "/api/kpis", "/api/uat/templates"):
        assert secured.get(path, headers=biz).status_code == 403, path
    assert secured.post("/api/run", json={"message": "hi"}, headers=biz).status_code == 403
    overview = secured.get(f"/api/onboardings/{mine.json()['id']}", headers=biz).json()
    assert "m2c" not in overview and overview["gates"] is None


def test_role_comes_from_the_account_not_the_request(secured: TestClient) -> None:
    admin = _login(secured, ADMIN_EMAIL, ADMIN_PASSWORD)
    biz = _make_user(secured, admin, "bg@dhl.test", "BUSINESS", ["BG"])
    case_id = secured.post("/api/onboardings", json={"ctry_cd": "BG", "title": "BG"}, headers=biz).json()["id"]
    secured.post(f"/api/onboardings/{case_id}/intake/form", headers=biz, json={"m2c": FULL_M2C,
        "description": "BG needs IOSS when SDT is present", "requirement_groups": ["IOSS"]})
    secured.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"}, headers=biz)
    spoofed = {**biz, "X-CCRE-Role": "CCRE_CONSULTANT"}
    resp = secured.post(f"/api/onboardings/{case_id}/transition", json={"name": "approve_requirement"},
                        headers=spoofed)
    assert resp.status_code == 409  # the header is ignored when sign-in is on


def test_change_password(secured: TestClient) -> None:
    admin = _login(secured, ADMIN_EMAIL, ADMIN_PASSWORD)
    wrong = secured.post("/api/auth/change-password", headers=admin,
                         json={"current_password": "x", "new_password": "NewPassword1"})
    assert wrong.status_code == 400
    ok = secured.post("/api/auth/change-password", headers=admin,
                      json={"current_password": ADMIN_PASSWORD, "new_password": "NewPassword1"})
    assert ok.status_code == 200
    _login(secured, ADMIN_EMAIL, "NewPassword1")
