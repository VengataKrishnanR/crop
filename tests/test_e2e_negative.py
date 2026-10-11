"""End-to-end refusals and edge cases through HTTP."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e_negative

BUSINESS = {"X-CCRE-Role": "BUSINESS"}
CONSULTANT = {"X-CCRE-Role": "CCRE_CONSULTANT"}
TEAM = {"X-CCRE-Role": "CCRE_TEAM"}
PM = {"X-CCRE-Role": "PM"}


def _new(client: TestClient, country: str = "BG") -> str:
    resp = client.post("/api/onboardings", json={"ctry_cd": country, "title": "t"}, headers=BUSINESS)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _form(client: TestClient, case_id: str) -> None:
    resp = client.post(f"/api/onboardings/{case_id}/intake/form", headers=BUSINESS, json={
        "description": "BG B2C needs IOSS when SDT is present", "requirement_groups": ["IOSS"]})
    assert resp.status_code == 200, resp.text


def test_requirement_cannot_be_submitted_before_it_is_captured(client: TestClient) -> None:
    case_id = _new(client)
    resp = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"},
                       headers=BUSINESS)
    assert resp.status_code == 409
    assert any("requirement" in r.lower() for r in resp.json()["detail"]["reasons"])


def test_pm_cannot_approve_the_requirement(client: TestClient) -> None:
    case_id = _new(client)
    _form(client, case_id)
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"}, headers=BUSINESS)
    resp = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "approve_requirement"},
                       headers=PM)
    assert resp.status_code == 409
    assert any("CCRE_CONSULTANT" in r for r in resp.json()["detail"]["reasons"])


def test_business_cannot_approve_the_timeline(client: TestClient) -> None:
    case_id = _new(client)
    _form(client, case_id)
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"}, headers=BUSINESS)
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "approve_requirement"}, headers=CONSULTANT)
    resp = client.post(f"/api/onboardings/{case_id}/timeline/generate", headers=BUSINESS,
                       json={"answers": {"requested_rtp": "2027-01-01", "earliest_start": "2026-11-02"}})
    assert resp.status_code == 403


def test_timeline_questionnaire_rejects_bad_answers(client: TestClient) -> None:
    case_id = _new(client)
    _form(client, case_id)
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"}, headers=BUSINESS)
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "approve_requirement"}, headers=CONSULTANT)
    missing = client.post(f"/api/onboardings/{case_id}/timeline/generate", json={"answers": {}}, headers=PM)
    assert missing.status_code == 400 and "requested go-live" in missing.json()["detail"]
    backwards = client.post(f"/api/onboardings/{case_id}/timeline/generate", headers=PM, json={
        "answers": {"requested_rtp": "2026-01-01", "earliest_start": "2026-11-02"}})
    assert backwards.status_code == 400
    # A late requested RTP is allowed but flagged as a risk
    tight = client.post(f"/api/onboardings/{case_id}/timeline/generate", headers=PM, json={
        "answers": {"requested_rtp": "2026-11-06", "earliest_start": "2026-11-02"}})
    assert tight.status_code == 200
    assert tight.json()["at_risk"] is True and tight.json()["risks"]
    # Manual edits must keep the milestone order
    milestones = tight.json()["milestones"]
    milestones[1]["start"], milestones[1]["end"] = "2026-10-01", "2026-10-02"
    edit = client.patch(f"/api/onboardings/{case_id}/timeline", headers=PM, json={"milestones": milestones})
    assert edit.status_code == 400


def test_bg_is_blocked_at_sanity_by_its_package_gap(client: TestClient, real_package_path: Path,
                                                   real_workbook_path: Path) -> None:
    client.post("/api/ingest/package", json={"path": str(real_package_path)})
    client.post("/api/ingest/workbook", json={"path": str(real_workbook_path)})
    case_id = _new(client)
    _form(client, case_id)
    for name, who in (("submit_requirement", BUSINESS), ("approve_requirement", CONSULTANT)):
        client.post(f"/api/onboardings/{case_id}/transition", json={"name": name}, headers=who)
    client.post(f"/api/onboardings/{case_id}/timeline/generate", headers=PM, json={"answers": {
        "requested_rtp": "2027-03-31", "earliest_start": "2026-11-02"}})
    for name in ("submit_timeline", "approve_timeline"):
        client.post(f"/api/onboardings/{case_id}/transition", json={"name": name}, headers=PM)
    client.post(f"/api/onboardings/{case_id}/m2c/start", headers=TEAM)
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "request_sanity_check"}, headers=TEAM)
    resp = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "sanity_passed"}, headers=TEAM)
    assert resp.status_code == 409
    reasons = " ".join(resp.json()["detail"]["reasons"])
    assert "blocking finding" in reasons and "package" in reasons
    # The failed sanity check is evidence: a validation run was persisted.
    report = client.post(f"/api/onboardings/{case_id}/m2c/validate", headers=TEAM).json()
    assert {f["code"].split("/")[0] for f in report["findings"] if f["severity"] == "blocker"} >= {"CHK015"}


def test_actions_need_the_right_stage(client: TestClient) -> None:
    case_id = _new(client)
    assert client.post(f"/api/onboardings/{case_id}/m2c/start", headers=TEAM).status_code == 409
    assert client.post(f"/api/onboardings/{case_id}/uat/runs", json={}, headers=TEAM).status_code == 409
    assert client.post(f"/api/onboardings/{case_id}/uat/test-cases/generate", json={},
                       headers=TEAM).status_code == 409


def test_business_reject_needs_a_comment(client: TestClient) -> None:
    from server.app import app
    from tools.core.db import get_session
    from tools.core.models import OnboardingCase, UatTestCase

    session = next(app.dependency_overrides[get_session]())
    case = OnboardingCase(code="NEG-TC", ctry_cd="DE", title="t", state="UAT_TC_REVIEW_BUSINESS")
    session.add(case)
    session.flush()
    tc = UatTestCase(case_id=case.id, test_id="T1", scenario="s", kind="positive", status="CCRE_APPROVED")
    session.add(tc)
    session.commit()
    assert client.patch(f"/api/uat/test-cases/{tc.id}", json={"status": "REJECTED"},
                        headers=BUSINESS).status_code == 400
    ok = client.patch(f"/api/uat/test-cases/{tc.id}", json={"status": "REJECTED", "comment": "wrong value"},
                      headers=BUSINESS)
    assert ok.status_code == 200 and ok.json()["status"] == "REJECTED"


def test_sample_payload_must_be_a_json_object(client: TestClient) -> None:
    assert client.post("/api/uat/templates", json={"name": "x", "body": "{not json"},
                       headers=TEAM).status_code == 400
    assert client.post("/api/uat/templates", json={"name": "x", "body": []}, headers=TEAM).status_code == 400
    ok = client.post("/api/uat/templates", json={"name": "Mine", "country": "de", "body": '{"a": 1}'},
                     headers=TEAM)
    assert ok.status_code == 201 and ok.json()["country"] == "DE"
    names = [t["name"] for t in client.get("/api/uat/templates", headers=TEAM).json()]
    assert "Mine" in names and any("Built-in" in n for n in names)


def test_advisory_layer_switched_off_is_a_clean_503(client: TestClient, monkeypatch) -> None:
    import server.advisory as advisory

    advisory._agent_module.cache_clear()
    monkeypatch.setattr("tools.agents.agents_available",
                        lambda: (False, "Advisory layer disabled by CCRE_AGENTS_ENABLED."))
    try:
        case_id = _new(client)
        resp = client.post(f"/api/onboardings/{case_id}/intake/chat", json={"message": "hi"}, headers=BUSINESS)
        assert resp.status_code == 503 and "disabled" in resp.json()["detail"]
        assert client.post("/api/run", json={"message": "hi"}, headers=TEAM).status_code == 503
    finally:
        advisory._agent_module.cache_clear()


def test_agent_that_never_returns_json_fails_after_one_retry(monkeypatch) -> None:
    from server import agent_invoker

    calls: list[str] = []

    def fake_collect(agent, prompt, session_id):
        calls.append(prompt)
        return "I am not JSON at all"

    monkeypatch.setattr(agent_invoker, "_collect_final_text", fake_collect)
    with pytest.raises(agent_invoker.AgentInvocationError, match="after retry"):
        agent_invoker.invoke_agent(object(), "do it", session_id="neg")
    assert len(calls) == 2 and "rejected with this error" in calls[1]


def test_unknown_static_asset_is_404(client: TestClient) -> None:
    assert client.get("/secrets.txt").status_code == 404
    assert client.get("/.env").status_code == 404
