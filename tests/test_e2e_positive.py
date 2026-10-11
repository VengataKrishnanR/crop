"""End-to-end happy paths through HTTP and the agents (stub LLM).

The advisory flow: interpret a requirement, draft rules, stage the proposal, have
a human accept it, see the validator run — and confirm that until acceptance the
rule tables are untouched.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e_positive

REQUIREMENT = (
    "Hi team, BG B2C shipments need the IOSS requirement raised when SDT is present "
    "and the service code is not DD. Effective from November."
)


def _new_case(client: TestClient, code: str = "ONB-2026-BG-100") -> dict:
    resp = client.post("/api/cases", json={"code": code, "ctry_cd": "BG", "title": "BG IOSS trigger"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _new_rule_set(client: TestClient, case_id: str) -> str:
    """A rule set to land accepted proposals in (the workbook normally provides one)."""
    from server.app import app
    from tools.core.db import get_session
    from tools.core.models import RuleSet

    session = next(app.dependency_overrides[get_session]())
    rs = RuleSet(version="v0.1", case_id=case_id)
    session.add(rs)
    session.commit()
    return rs.id


def test_ui_and_agent_registry_are_served(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "CCRE" in index.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200

    registry = client.get("/api/agents").json()
    assert registry["llm_mode"] == "stub"
    assert registry["available"] is True
    assert set(registry["agents"]) == {
        "requirement_interpreter", "rule_drafter", "test_case_designer", "failure_analyst",
    }


def test_interpret_then_draft_then_accept(client: TestClient) -> None:
    case = _new_case(client)

    # 1. Interpret — recorded on the audit trail, gate stated.
    interp = client.post(f"/api/cases/{case['id']}/interpret",
                         json={"requirement_text": REQUIREMENT, "actor": "hristina"})
    assert interp.status_code == 200, interp.text
    body = interp.json()
    assert body["interpretation"]["country_code"] == "BG"
    assert "IOSS" in body["interpretation"]["requirement_groups"]
    assert "PM" in body["gate"]

    # 2. Draft — staged as a PROPOSED proposal, never applied.
    draft = client.post(f"/api/cases/{case['id']}/draft-rules",
                        json={"interpretation": body["interpretation"], "actor": "priyanka"})
    assert draft.status_code == 200, draft.text
    staged = draft.json()
    assert staged["staged"] is True and staged["status"] == "PROPOSED"
    proposal_id = staged["proposal_id"]

    proposals = client.get(f"/api/cases/{case['id']}/proposals").json()
    assert [p["id"] for p in proposals] == [proposal_id]

    rule_set_id = _new_rule_set(client, case["id"])
    assert client.get(f"/api/rule-sets/{rule_set_id}/rules").json() == []

    # 3. A human accepts — only now do rules exist, and validation runs at once.
    accepted = client.post(f"/api/proposals/{proposal_id}/decide",
                           json={"accept": True, "actor": "jon", "rule_set_id": rule_set_id})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["rules_created"]
    assert "validation" in accepted.json()
    assert len(client.get(f"/api/rule-sets/{rule_set_id}/rules").json()) >= 1

    # Every agent step is on the record, attributed to the agent.
    actions = {e["action"] for e in client.get(f"/api/cases/{case['id']}/audit").json()["events"]}
    assert {"advisory:interpretation", "advisory:change_set_staged", "proposal:accepted"} <= actions


def test_draft_from_requirement_text_alone(client: TestClient) -> None:
    case = _new_case(client, "ONB-2026-BG-101")
    draft = client.post(f"/api/cases/{case['id']}/draft-rules",
                        json={"requirement_text": REQUIREMENT})
    assert draft.status_code == 200, draft.text
    assert draft.json()["rules_proposed"] >= 1


def test_design_test_suite_for_a_rule_set(client: TestClient) -> None:
    case = _new_case(client, "ONB-2026-BG-102")
    rule_set_id = _new_rule_set(client, case["id"])
    proposal = client.post(f"/api/cases/{case['id']}/draft-rules",
                           json={"requirement_text": REQUIREMENT}).json()
    client.post(f"/api/proposals/{proposal['proposal_id']}/decide",
                json={"accept": True, "actor": "jon", "rule_set_id": rule_set_id})

    suite = client.post(f"/api/rule-sets/{rule_set_id}/test-suite", json={"country": "BG"})
    assert suite.status_code == 200, suite.text
    cases = suite.json()["suite"]["cases"]
    assert {c["kind"] for c in cases} >= {"positive", "negative"}


def test_failure_analysis_recommends_without_touching_rules(client: TestClient) -> None:
    result = client.post("/api/failures/analyse", json={
        "test_id": "BG-IOSS-01", "expected": "IOSS raised", "actual": "no case created",
    })
    assert result.status_code == 200, result.text
    analysis = result.json()["analysis"]
    assert analysis["test_id"] == "BG-IOSS-01"
    assert analysis["change_rules"] is False


def test_chat_with_the_orchestrator(client: TestClient) -> None:
    session_id = client.post("/api/session").json()["session_id"]
    hello = client.post("/api/run", json={"message": "hello", "session_id": session_id}).json()
    assert hello["session_id"] == session_id
    assert "CCRE onboarding assistant" in hello["response"]

    delegated = client.post("/api/run", json={"message": REQUIREMENT}).json()
    assert "requirement_interpreter" in delegated["response"]
