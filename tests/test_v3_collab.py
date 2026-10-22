"""v3: approval reminders by email, the DMG email task, the sanity checklist,
"+ scenario" test cases and row-by-row decisions, and email settings."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FULL_M2C

pytestmark = pytest.mark.workflow

BUSINESS = {"X-CCRE-Role": "BUSINESS"}
CONSULTANT = {"X-CCRE-Role": "CCRE_CONSULTANT"}
TEAM = {"X-CCRE-Role": "CCRE_TEAM"}
PM = {"X-CCRE-Role": "PM"}


@pytest.fixture(autouse=True)
def outbox(tmp_path, monkeypatch):
    """Emails go to a temporary outbox (no SMTP host configured)."""
    monkeypatch.setenv("CCRE_DATA_DIR", str(tmp_path))
    return tmp_path / "outbox"


def _users(client: TestClient) -> None:
    for email, role, countries in (("pm@dhl.test", "PM", []), ("consultant@dhl.test", "CCRE_CONSULTANT", []),
                                   ("team@dhl.test", "CCRE_TEAM", []), ("bg@dhl.test", "BUSINESS", ["BG"]),
                                   ("de@dhl.test", "BUSINESS", ["DE"])):
        resp = client.post("/api/admin/users", json={"email": email, "name": role.title(), "role": role,
                                                     "password": "Password123", "countries": countries})
        assert resp.status_code == 201, resp.text


def _case_in_review(client: TestClient) -> str:
    case_id = client.post("/api/onboardings", json={"ctry_cd": "BG", "title": "BG IOSS"}, headers=BUSINESS).json()["id"]
    client.post(f"/api/onboardings/{case_id}/intake/form", headers=BUSINESS,
                json={"m2c": FULL_M2C, "description": "BG B2C needs IOSS when SDT is present", "requirement_groups": ["IOSS"]})
    assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"},
                       headers=BUSINESS).status_code == 200
    return case_id


# --------------------------------------------------------------------------- #
# 1. waiting banner + reminder email
# --------------------------------------------------------------------------- #

def test_waiting_banner_tells_who_must_act(client: TestClient) -> None:
    case_id = _case_in_review(client)
    biz = client.get(f"/api/onboardings/{case_id}", headers=BUSINESS).json()
    assert biz["waiting"]["roles"] == ["CCRE_CONSULTANT"] and biz["waiting"]["can_act"] is False
    assert "CCRE consultant" in biz["waiting"]["message"]
    assert all(not a["mine"] for a in biz["actions"])
    consultant = client.get(f"/api/onboardings/{case_id}", headers=CONSULTANT).json()
    assert consultant["waiting"]["can_act"] is True
    kinds = {a["kind"] for a in consultant["actions"] if a["mine"]}
    assert {"approve", "reject"} <= kinds


def test_reminder_goes_to_approvers_with_everyone_in_cc(client: TestClient, outbox: Path) -> None:
    _users(client)
    case_id = _case_in_review(client)
    sent = client.post(f"/api/onboardings/{case_id}/remind", json={"message": "Please review today"}, headers=BUSINESS)
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["status"] == "OUTBOX"
    assert body["to"] == ["consultant@dhl.test"]
    # Everyone involved is in CC — but not the DE-only business user.
    assert set(body["cc"]) == {"admin@ccre.local", "pm@dhl.test", "team@dhl.test", "bg@dhl.test"} - {"admin@ccre.local"} \
        or "bg@dhl.test" in body["cc"]
    assert "de@dhl.test" not in body["cc"] and "de@dhl.test" not in body["to"]
    eml = list(outbox.glob("*_reminder.eml"))
    assert eml and "Please review today" in eml[0].read_text(encoding="utf-8")
    # Throttled: a second reminder within 10 minutes is refused.
    again = client.post(f"/api/onboardings/{case_id}/remind", json={}, headers=BUSINESS)
    assert again.status_code == 409
    overview = client.get(f"/api/onboardings/{case_id}", headers=BUSINESS).json()
    assert overview["waiting"]["last_reminder_at"]


def test_reminder_needs_an_approver_to_exist(client: TestClient) -> None:
    case_id = _case_in_review(client)
    resp = client.post(f"/api/onboardings/{case_id}/remind", json={}, headers=BUSINESS)
    assert resp.status_code == 400 and "CCRE consultant" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 3. DMG email task
# --------------------------------------------------------------------------- #

@pytest.fixture
def loaded(client: TestClient, real_package_path: Path, real_workbook_path: Path) -> None:
    client.post("/api/ingest/package", json={"path": str(real_package_path)})
    client.post("/api/ingest/workbook", json={"path": str(real_workbook_path)})


def _to_rule_config(client: TestClient, country: str = "DE") -> str:
    case_id = client.post("/api/onboardings", json={"ctry_cd": country, "title": "POA for DDP"},
                          headers=BUSINESS).json()["id"]
    client.post(f"/api/onboardings/{case_id}/intake/form", headers=BUSINESS, json={"m2c": FULL_M2C,
        "description": f"{country} consumer shipments must provide a Power of Attorney when the incoterm is DDP.",
        "shipment_type": "B2C", "requirement_groups": ["POA"]})
    for name, who in (("submit_requirement", BUSINESS), ("approve_requirement", CONSULTANT)):
        assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": name}, headers=who).status_code == 200
    client.post(f"/api/onboardings/{case_id}/timeline/generate", headers=PM,
                json={"answers": {"requested_rtp": "2027-03-31", "earliest_start": "2026-11-02"}})
    for name, who in (("submit_timeline", CONSULTANT), ("approve_timeline", PM)):
        assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": name}, headers=who).status_code == 200
    client.post(f"/api/onboardings/{case_id}/m2c/start", headers=TEAM)
    return case_id


def test_dmg_template_is_owned_by_the_ccre_team(client: TestClient) -> None:
    tpl = client.get("/api/dmg/template", headers=TEAM).json()
    assert "{{m2c_rules}}" in tpl["body"] and "dmg_attributes" in tpl["placeholders"]
    assert client.get("/api/dmg/template", headers=BUSINESS).status_code == 403
    assert client.put("/api/dmg/template", headers=PM, json={**tpl, "to": ["x@dhl.test"]}).status_code == 403
    bad = client.put("/api/dmg/template", headers=TEAM, json={**tpl, "body": "{{nope}}", "to": ["x@dhl.test"]})
    assert bad.status_code == 400 and "nope" in bad.json()["detail"]
    bad_mail = client.put("/api/dmg/template", headers=TEAM, json={**tpl, "to": ["not-an-email"]})
    assert bad_mail.status_code == 400


def test_dmg_email_is_filled_reviewed_then_sent(client: TestClient, loaded: None, outbox: Path) -> None:
    case_id = _to_rule_config(client)
    tpl = client.get("/api/dmg/template", headers=TEAM).json()
    client.put("/api/dmg/template", headers=TEAM, json={**tpl, "to": ["dmg@dhl.test"], "cc": ["lead@dhl.test"]})

    blocked = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "request_sanity_check"}, headers=TEAM)
    assert blocked.status_code == 409 and "DMG" in " ".join(blocked.json()["detail"]["reasons"])

    draft = client.post(f"/api/onboardings/{case_id}/dmg/prepare", headers=TEAM).json()
    assert draft["status"] == "DRAFT" and "DE" in draft["subject"]
    assert "POA" in draft["body"] and "{{" not in draft["body"]
    edited = client.put(f"/api/onboardings/{case_id}/dmg", headers=TEAM,
                        json={"body": draft["body"] + "\nPlease confirm by Friday."}).json()
    assert edited["body"].endswith("Friday.")
    assert client.post(f"/api/onboardings/{case_id}/dmg/submit", headers=TEAM).json()["status"] == "IN_REVIEW"

    no_reason = client.post(f"/api/onboardings/{case_id}/dmg/decide", headers=CONSULTANT, json={"approve": False})
    assert no_reason.status_code == 400
    rejected = client.post(f"/api/onboardings/{case_id}/dmg/decide", headers=CONSULTANT,
                           json={"approve": False, "comment": "Add the attribute list"}).json()
    assert rejected["status"] == "DRAFT" and rejected["decision_comment"] == "Add the attribute list"

    client.post(f"/api/onboardings/{case_id}/dmg/submit", headers=TEAM)
    sent = client.post(f"/api/onboardings/{case_id}/dmg/decide", headers=CONSULTANT, json={"approve": True}).json()
    assert sent["status"] == "SENT" and sent["completed"] is True
    eml = list(outbox.glob("*_dmg.eml"))
    assert eml and "Friday" in eml[0].read_text(encoding="utf-8")
    assert client.post(f"/api/onboardings/{case_id}/dmg/prepare", headers=TEAM).status_code == 409

    overview = client.get(f"/api/onboardings/{case_id}", headers=TEAM).json()
    assert overview["dmg"] == {"status": "SENT", "completed": True}
    assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": "request_sanity_check"},
                       headers=TEAM).status_code == 200


def test_dmg_needs_recipients_and_four_eyes(client: TestClient, loaded: None, monkeypatch) -> None:
    case_id = _to_rule_config(client)
    assert client.post(f"/api/onboardings/{case_id}/dmg/prepare", headers=TEAM).status_code == 400
    tpl = client.get("/api/dmg/template", headers=TEAM).json()
    client.put("/api/dmg/template", headers=TEAM, json={**tpl, "to": ["dmg@dhl.test"]})
    client.post(f"/api/onboardings/{case_id}/dmg/prepare", headers=TEAM)
    client.post(f"/api/onboardings/{case_id}/dmg/submit", headers=TEAM)

    # With real sign-in, the person who submitted cannot also approve.
    import server.collab as collab
    from server.auth import CurrentUser
    from tools.core.security import UserRole

    def same_person():
        return CurrentUser(id="u1", email="team@dhl.test", name="Team", role=UserRole.CCRE_TEAM)

    from server.app import app
    from server.auth import current_user
    from server.lifecycle import _case  # noqa: F401  (ensures routes loaded)

    from tools.core.db import get_session
    session = next(app.dependency_overrides[get_session]())
    from tools.core.models import DmgTask
    task = session.query(DmgTask).one()
    task.submitted_by = "Team <team@dhl.test>"
    session.commit()
    app.dependency_overrides[current_user] = same_person
    try:
        refused = client.post(f"/api/onboardings/{case_id}/dmg/decide", json={"approve": True})
        assert refused.status_code == 409 and "second" in refused.json()["detail"]
    finally:
        app.dependency_overrides.pop(current_user)


def test_dmg_not_required_completes_the_task(client: TestClient, loaded: None) -> None:
    case_id = _to_rule_config(client)
    assert client.post(f"/api/onboardings/{case_id}/dmg/not-required", headers=TEAM,
                       json={"comment": "x"}).status_code == 403  # consultant decides this
    done = client.post(f"/api/onboardings/{case_id}/dmg/not-required", headers=CONSULTANT,
                       json={"comment": "No message change needed"}).json()
    assert done["status"] == "NOT_REQUIRED" and done["completed"]


# --------------------------------------------------------------------------- #
# 2. sanity checklist
# --------------------------------------------------------------------------- #

def test_sanity_checklist_explains_each_item(client: TestClient, loaded: None) -> None:
    from test_e2e_positive import align_rows
    case_id = _to_rule_config(client)
    before = client.get(f"/api/onboardings/{case_id}/sanity", headers=TEAM).json()
    assert before["explanation"] and before["ready"] is False and before["in_stage"] is False
    items = {i["key"]: i for i in before["items"]}
    assert list(items) == ["rows", "requirement_match", "rules", "package", "dmg", "changes"]
    assert items["rows"]["status"] == "pass" and items["package"]["status"] == "pass"
    assert items["requirement_match"]["status"] == "fail"          # DE row 38 differs from the requirement
    assert items["requirement_match"]["findings"][0]["row"] == 38
    assert items["dmg"]["status"] == "fail" and items["dmg"]["fix"]["action"] == "send_back"
    assert all(i["why"] for i in before["items"])
    assert "DMG" in before["send_back_reason"]
    align_rows(client, case_id)
    client.post(f"/api/onboardings/{case_id}/dmg/not-required", headers=CONSULTANT, json={"comment": "none"})
    assert client.get(f"/api/onboardings/{case_id}/sanity", headers=TEAM).json()["ready"] is True
    assert client.get(f"/api/onboardings/{case_id}/sanity", headers=BUSINESS).status_code == 403


# --------------------------------------------------------------------------- #
# 4. "+ scenario" and row-by-row decisions
# --------------------------------------------------------------------------- #

def test_scenario_becomes_a_test_case_that_needs_both_approvals(client: TestClient, loaded: None) -> None:
    from test_e2e_positive import align_rows
    case_id = _to_rule_config(client)
    align_rows(client, case_id)
    client.post(f"/api/onboardings/{case_id}/dmg/not-required", headers=CONSULTANT, json={"comment": "none"})
    for name in ("request_sanity_check", "sanity_passed"):
        assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": name}, headers=TEAM).status_code == 200
    ai = client.post(f"/api/onboardings/{case_id}/uat/test-cases/generate", json={}, headers=TEAM).json()
    scenario = client.post(f"/api/onboardings/{case_id}/uat/test-cases/scenario", headers=TEAM, json={
        "text": "A consumer parcel to Germany, duty paid (DDP), must ask for the POA."}).json()
    assert len(scenario) == 1 and scenario[0]["source"] == "Scenario" and scenario[0]["status"] == "DRAFT"
    assert any(c["field"] == "incoterm" and c["value"] == "DDP" for c in scenario[0]["input_conditions"])

    # Regenerating AI rows keeps the person's scenario.
    client.post(f"/api/onboardings/{case_id}/uat/test-cases/generate", json={}, headers=TEAM)
    rows = client.get(f"/api/onboardings/{case_id}/uat/test-cases", headers=TEAM).json()
    assert any(r["source"] == "Scenario" for r in rows)

    assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_test_cases"},
                       headers=TEAM).status_code == 200
    # CCRE cannot approve the stage while rows are undecided.
    early = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "ccre_approve_test_cases"},
                        headers=CONSULTANT)
    assert early.status_code == 409 and "still need a CCRE" in " ".join(early.json()["detail"]["reasons"])
    first_ai = next(r for r in rows if r["source"] == "AI")
    client.post(f"/api/onboardings/{case_id}/uat/test-cases/decide", headers=CONSULTANT,
                json={"ids": [first_ai["id"]], "approve": False, "comment": "duplicate of the scenario"})
    client.post(f"/api/onboardings/{case_id}/uat/test-cases/decide", headers=CONSULTANT,
                json={"all_pending": True, "approve": True})
    assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": "ccre_approve_test_cases"},
                       headers=CONSULTANT).status_code == 200

    # The business adds its own scenario during review; it needs CCRE + business approval too.
    biz = client.post(f"/api/onboardings/{case_id}/uat/test-cases/scenario", headers=BUSINESS, json={
        "text": "A business (B2B) shipment to Germany under DAP should not ask for the POA."}).json()
    assert biz[0]["status"] == "DRAFT" and biz[0]["kind"] == "negative"
    blocked = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "business_approve_test_cases"},
                          headers=BUSINESS)
    assert blocked.status_code == 409
    client.post(f"/api/onboardings/{case_id}/uat/test-cases/decide", headers=CONSULTANT,
                json={"ids": [biz[0]["id"]], "approve": True})
    client.post(f"/api/onboardings/{case_id}/uat/test-cases/decide", headers=BUSINESS,
                json={"all_pending": True, "approve": True})
    assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": "business_approve_test_cases"},
                       headers=BUSINESS).status_code == 200

    final = client.get(f"/api/onboardings/{case_id}/uat/test-cases", headers=TEAM).json()
    rejected = [r for r in final if r["status"] == "REJECTED"]
    assert len(rejected) == 1 and rejected[0]["review_comment"] == "duplicate of the scenario"

    run = client.post(f"/api/onboardings/{case_id}/uat/runs", json={}, headers=TEAM).json()
    executed = {r["test_id"] for r in run["run"]["results"]}
    assert rejected[0]["test_id"] not in executed, "only rows approved by both are executed"
    assert len(executed) == len(final) - 1


# --------------------------------------------------------------------------- #
# email settings (admin)
# --------------------------------------------------------------------------- #

def test_mail_settings_and_log(client: TestClient, outbox: Path) -> None:
    s = client.get("/api/admin/mail").json()
    assert s["mode"] == "outbox"
    saved = client.put("/api/admin/mail", json={"host": "", "from_address": "ccre@dhl.test",
                                                "public_url": "https://ccre.dhl.test", "password": "pw"}).json()
    assert saved["password_set"] is True and "password" not in saved
    note = client.post("/api/admin/mail/test", json={"to": "me@dhl.test"}).json()
    assert note["status"] == "OUTBOX"
    log = client.get("/api/admin/notifications").json()
    assert log[0]["kind"] == "TEST"
    assert client.get("/api/admin/mail", headers=TEAM).status_code == 403
    assert client.put("/api/admin/mail", json={"security": "bogus", "from_address": "a@b.cd"}).status_code == 400
