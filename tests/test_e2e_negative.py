"""End-to-end refusals and edge cases through HTTP and the agents."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.e2e_negative


def test_unknown_case_is_404_for_every_advisory_call(client: TestClient) -> None:
    assert client.post("/api/cases/nope/interpret", json={"requirement_text": "x"}).status_code == 404
    assert client.post("/api/cases/nope/draft-rules", json={"requirement_text": "x"}).status_code == 404
    assert client.post("/api/rule-sets/nope/test-suite", json={}).status_code == 404
    assert client.post("/api/failures/analyse",
                       json={"test_id": "T1", "case_id": "nope"}).status_code == 404


def test_empty_inputs_are_rejected(client: TestClient) -> None:
    case = client.post("/api/cases", json={"code": "ONB-NEG-1", "ctry_cd": "BG", "title": "t"}).json()
    assert client.post(f"/api/cases/{case['id']}/interpret",
                       json={"requirement_text": ""}).status_code == 422
    # No requirement text on the case and none supplied: nothing to draft from.
    refused = client.post(f"/api/cases/{case['id']}/draft-rules", json={})
    assert refused.status_code == 400
    assert client.post("/api/run", json={"message": "   "}).status_code == 400
    assert client.post("/api/failures/analyse", json={"test_id": ""}).status_code == 422


def test_test_suite_needs_rules_in_scope(client: TestClient) -> None:
    from server.app import app
    from tools.core.db import get_session
    from tools.core.models import RuleSet

    session = next(app.dependency_overrides[get_session]())
    rs = RuleSet(version="v-empty")
    session.add(rs)
    session.commit()
    resp = client.post(f"/api/rule-sets/{rs.id}/test-suite", json={})
    assert resp.status_code == 400
    assert "No rules" in resp.json()["detail"]


def test_proposal_cannot_be_decided_twice(client: TestClient) -> None:
    case = client.post("/api/cases", json={"code": "ONB-NEG-2", "ctry_cd": "BG", "title": "t"}).json()
    proposal = client.post(f"/api/cases/{case['id']}/draft-rules",
                           json={"requirement_text": "BG needs IOSS"}).json()
    first = client.post(f"/api/proposals/{proposal['proposal_id']}/decide",
                        json={"accept": False, "actor": "jon"})
    assert first.status_code == 200
    second = client.post(f"/api/proposals/{proposal['proposal_id']}/decide",
                         json={"accept": False, "actor": "jon"})
    assert second.status_code == 409


def test_advisory_layer_switched_off_is_a_clean_503(client: TestClient, monkeypatch) -> None:
    import server.advisory as advisory

    advisory._agent_module.cache_clear()
    monkeypatch.setattr("tools.agents.agents_available",
                        lambda: (False, "Advisory layer disabled by CCRE_AGENTS_ENABLED."))
    try:
        case = client.post("/api/cases", json={"code": "ONB-NEG-3", "ctry_cd": "BG", "title": "t"}).json()
        resp = client.post(f"/api/cases/{case['id']}/interpret", json={"requirement_text": "BG IOSS"})
        assert resp.status_code == 503
        assert "disabled" in resp.json()["detail"]
        assert client.post("/api/run", json={"message": "hi"}).status_code == 503
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
    assert len(calls) == 2
    assert "rejected with this error" in calls[1]


def test_unknown_static_asset_is_404(client: TestClient) -> None:
    assert client.get("/secrets.txt").status_code == 404
    assert client.get("/.env").status_code == 404
