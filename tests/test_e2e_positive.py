"""End-to-end onboarding through HTTP, each step done by the role that owns it.

Uses the real reference artifacts (skips without them) and the stub LLM, so the
agents, the mock CCRE endpoint and every gate run for real. DE is used because
its requirement group is mapped in the config package, so UAT can genuinely pass.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FULL_M2C

pytestmark = pytest.mark.e2e_positive

BUSINESS = {"X-CCRE-Role": "BUSINESS"}
CONSULTANT = {"X-CCRE-Role": "CCRE_CONSULTANT"}
TEAM = {"X-CCRE-Role": "CCRE_TEAM"}
PM = {"X-CCRE-Role": "PM"}

ANSWERS = {
    "requested_rtp": "2027-03-31", "earliest_start": "2026-11-02", "ccre_capacity": 2,
    "dmg_change_required": "no", "package_rebuild_days": 5, "business_review_days": 3,
    "business_signoff_days": 3, "uat_environment_ready": "yes", "blackout_dates": "2026-12-25",
    "priority": "high",
}


@pytest.fixture
def loaded(client: TestClient, real_package_path: Path, real_workbook_path: Path) -> None:
    assert client.post("/api/ingest/package", json={"path": str(real_package_path)}).status_code == 200
    assert client.post("/api/ingest/workbook", json={"path": str(real_workbook_path)}).status_code == 200


def _go(client: TestClient, case_id: str, name: str, who: dict, **body) -> dict:
    resp = client.post(f"/api/onboardings/{case_id}/transition", json={"name": name, **body}, headers=who)
    assert resp.status_code == 200, f"{name}: {resp.text}"
    return resp.json()


def _onboard_to_uat_execution(client: TestClient) -> str:
    """Drive a DE onboarding from intake to UAT execution. Returns the case id."""
    case = client.post("/api/onboardings", json={"ctry_cd": "DE", "title": "DE POA for DDP"},
                       headers=BUSINESS)
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    assert case.json()["state"] == "INTAKE" and case.json()["code"].startswith("ONB-")

    # 1. Intake by form + NLP (business team)
    # The DDP condition comes from the condition builder (incoterm is one of DDP).
    m2c = {**FULL_M2C, "conditions": [[{"field": "incoterm", "op": "any", "values": ["DDP"]}]]}
    form = client.post(f"/api/onboardings/{case_id}/intake/form", headers=BUSINESS, json={"m2c": m2c,
        "description": "DE consumer shipments must provide a Power of Attorney when the incoterm is DDP.",
        "shipment_type": "B2C", "requirement_groups": ["POA"], "requested_rtp": "2027-03-31",
        "business_owner": "Anna Schmidt"})
    assert form.status_code == 200, form.text
    req = form.json()["requirement"]
    assert req["mode"] == "FORM" and "POA" in req["structured"]["requirement_groups"]
    assert req["structured"]["country_code"] == "DE"

    _go(client, case_id, "submit_requirement", BUSINESS)
    _go(client, case_id, "approve_requirement", CONSULTANT)

    # 2. Timeline: PM answers the questionnaire, AI plans, PM approves → published
    tl = client.post(f"/api/onboardings/{case_id}/timeline/generate", json={"answers": ANSWERS}, headers=PM)
    assert tl.status_code == 200, tl.text
    stages = [m["stage"] for m in tl.json()["milestones"]]
    assert stages == ["RULE_CONFIG_DMG", "SANITY_CHECK", "UAT_TC_PREP", "UAT_TC_REVIEW",
                      "UAT_EXECUTION", "UAT_REVIEW_SIGNOFF", "RTP"]
    assert all(m["start"] != "2026-12-25" for m in tl.json()["milestones"])
    # Business cannot see a draft timeline …
    assert client.get(f"/api/onboardings/{case_id}/timeline", headers=BUSINESS).json() is None
    _go(client, case_id, "submit_timeline", CONSULTANT)
    _go(client, case_id, "approve_timeline", PM)
    # … but sees the approved one.
    published = client.get(f"/api/onboardings/{case_id}/timeline", headers=BUSINESS).json()
    assert published["status"] == "APPROVED"

    # 3. Rule config + DMG: M2C draft seeded from the workbook's DE rows
    start = client.post(f"/api/onboardings/{case_id}/m2c/start", headers=TEAM)
    assert start.status_code == 200, start.text
    assert start.json()["rules_copied"] >= 1
    # AI draft is staged as a proposal; the CCRE team rejects it (keeps the workbook rule)
    draft = client.post(f"/api/onboardings/{case_id}/m2c/draft", json={}, headers=TEAM)
    assert draft.status_code == 200, draft.text
    assert draft.json()["status"] == "PROPOSED"
    decided = client.post(f"/api/proposals/{draft.json()['proposal_id']}/decide",
                          json={"accept": False, "actor": "ccre-team"}, headers=TEAM)
    assert decided.status_code == 200

    # Test preparation may start while the M2C is still in configuration
    early = client.post(f"/api/onboardings/{case_id}/uat/test-cases/generate", json={}, headers=TEAM)
    assert early.status_code == 200, early.text

    align_rows(client, case_id)
    complete_dmg(client, case_id)
    _go(client, case_id, "request_sanity_check", TEAM)
    sanity = client.get(f"/api/onboardings/{case_id}/sanity", headers=TEAM).json()
    assert sanity["ready"], sanity
    _go(client, case_id, "sanity_passed", TEAM)

    # 4. UAT test cases: generate, CCRE review, business review
    cases = client.post(f"/api/onboardings/{case_id}/uat/test-cases/generate", json={}, headers=TEAM)
    assert cases.status_code == 200, cases.text
    kinds = {c["kind"] for c in cases.json()}
    assert {"positive", "negative"} <= kinds
    assert all(c["business_summary"] for c in cases.json())
    # Business cannot see test cases before their review step
    assert client.get(f"/api/onboardings/{case_id}/uat/test-cases", headers=BUSINESS).json() == []
    _go(client, case_id, "submit_test_cases", TEAM)
    approve_rows(client, case_id, CONSULTANT)
    _go(client, case_id, "ccre_approve_test_cases", CONSULTANT)
    business_view = client.get(f"/api/onboardings/{case_id}/uat/test-cases", headers=BUSINESS).json()
    assert business_view and "input_conditions" not in business_view[0]  # business fields only
    approve_rows(client, case_id, BUSINESS)
    _go(client, case_id, "business_approve_test_cases", BUSINESS)
    return case_id


def align_rows(client: TestClient, case_id: str) -> None:
    """CCRE team: make the rows for the requirement's groups say what the requirement says.

    The DE POA workbook row is bound to a newer definition (b5a141ed…) than the 2.10.4 test package
    ships, so — as in real life — a consultant accepts that package gap as an exception."""
    req = client.get(f"/api/onboardings/{case_id}/intake", headers=TEAM).json()["requirement"]["structured"]
    groups = set((req.get("m2c") or {}).get("requirement_groups") or req.get("requirement_groups") or [])
    for row in client.get(f"/api/onboardings/{case_id}/rule-config", headers=TEAM).json()["rows"]:
        if row["sirg_cd"] in groups:
            resp = client.post(f"/api/onboardings/{case_id}/rule-config/rows/{row['id']}/align-requirement",
                               headers=TEAM)
            assert resp.status_code == 200, resp.text
    sanity = client.get(f"/api/onboardings/{case_id}/sanity", headers=TEAM).json()
    if any(i["key"] == "package" and i["status"] == "fail" for i in sanity["items"]):
        resp = client.post(f"/api/onboardings/{case_id}/sanity/waivers", headers=CONSULTANT, json={
            "item_key": "package", "reason": "Workbook uses a newer definition than the test package",
            "reference": "TEST-PKG"})
        assert resp.status_code == 200, resp.text


def complete_dmg(client: TestClient, case_id: str) -> None:
    """CCRE team: template recipients, prepare, submit; a reviewer approves → sent."""
    tpl = client.get("/api/dmg/template", headers=TEAM).json()
    client.put("/api/dmg/template", headers=TEAM, json={
        "subject": tpl["subject"], "body": tpl["body"], "to": ["dmg-team@dhl.test"], "cc": ["ccre@dhl.test"]})
    assert client.post(f"/api/onboardings/{case_id}/dmg/prepare", headers=TEAM).status_code == 200
    assert client.post(f"/api/onboardings/{case_id}/dmg/submit", headers=TEAM).status_code == 200
    sent = client.post(f"/api/onboardings/{case_id}/dmg/decide", headers=CONSULTANT, json={"approve": True})
    assert sent.status_code == 200 and sent.json()["status"] == "SENT", sent.text


def approve_rows(client: TestClient, case_id: str, who: dict) -> None:
    resp = client.post(f"/api/onboardings/{case_id}/uat/test-cases/decide", headers=who,
                       json={"all_pending": True, "approve": True})
    assert resp.status_code == 200, resp.text


def test_full_onboarding_from_intake_to_rtp(client: TestClient, loaded: None) -> None:
    case_id = _onboard_to_uat_execution(client)

    # 5. UAT execution: payloads generated, executed against mock CCRE, reviewed
    run = client.post(f"/api/onboardings/{case_id}/uat/runs", json={}, headers=TEAM)
    assert run.status_code == 200, run.text
    body = run.json()
    results = body["run"]["results"]
    assert results and all(r["verdict"] == "PASS" for r in results), results
    assert all(r["verdict_source"] == "deterministic" for r in results)
    assert all(r["payload"]["destinationCountry"] == "DE" for r in results)
    # Execution complete → handed to the CCRE team automatically
    assert body["state"] == "UAT_RESULT_REVIEW"

    # 6. CCRE reviews first, then business signs off
    assert client.get(f"/api/onboardings/{case_id}/uat/runs", headers=BUSINESS).json() == []
    _go(client, case_id, "ccre_accept_results", TEAM)
    business_runs = client.get(f"/api/onboardings/{case_id}/uat/runs", headers=BUSINESS).json()
    assert business_runs[0]["results"][0]["business_explanation"]
    assert "payload" not in business_runs[0]["results"][0]
    _go(client, case_id, "business_signoff", BUSINESS)

    # 7. RTP
    final = _go(client, case_id, "confirm_production", TEAM)
    assert final["state"] == "COMPLETED"

    overview = client.get(f"/api/onboardings/{case_id}", headers=TEAM).json()
    rtp = next(m for m in overview["timeline"]["milestones"] if m["stage"] == "RTP")
    assert rtp["actual_end"], "RTP actual date is recorded"

    kpis = client.get("/api/kpis", headers=PM).json()
    assert kpis["summary"]["completed"] == 1
    assert kpis["summary"]["first_run_pass_rate_pct"] == 100.0
    assert kpis["summary"]["m2c_first_time_right_pct"] == 100.0
    row = next(r for r in kpis["cases"] if r["id"] == case_id)
    assert row["cycles"] == 1 and row["rule_coverage_pct"] == 100.0


def test_failed_uat_loops_back_to_rule_config(client: TestClient, loaded: None) -> None:
    case_id = _onboard_to_uat_execution(client)

    # Break the M2C rule after approval: the positive test must now fail.
    m2c = client.get(f"/api/onboardings/{case_id}/m2c", headers=TEAM).json()
    rule = m2c["rules"][0]
    original = rule["other_logic"]
    broken = client.patch(f"/api/rules/{rule['id']}", headers=TEAM,
                          json={"other_logic": 'incotermCodeList.contains("EXW")', "actor": "t"})
    assert broken.status_code == 200

    run = client.post(f"/api/onboardings/{case_id}/uat/runs", json={}, headers=TEAM).json()
    failed = [r for r in run["run"]["results"] if r["verdict"] != "PASS"]
    assert failed, "the broken rule must fail the positive test"

    # The CCRE team cannot accept failing results …
    refused = client.post(f"/api/onboardings/{case_id}/transition", headers=TEAM,
                          json={"name": "ccre_accept_results"})
    assert refused.status_code == 409
    # … asks the failure analyst …
    analysis = client.post(f"/api/uat/results/{failed[0]['id']}/analyse", headers=TEAM)
    assert analysis.status_code == 200, analysis.text
    assert analysis.json()["analysis"]["change_rules"] in (True, False)
    # … and sends it back: the cycle restarts at rule config.
    back = _go(client, case_id, "request_correction", TEAM, comment="positive case failed")
    assert back["state"] == "RULE_CONFIG"

    client.patch(f"/api/rules/{rule['id']}", headers=TEAM, json={"other_logic": original, "actor": "t"})
    _go(client, case_id, "request_sanity_check", TEAM)
    _go(client, case_id, "sanity_passed", TEAM)
    _go(client, case_id, "submit_test_cases", TEAM)
    _go(client, case_id, "ccre_approve_test_cases", CONSULTANT)
    _go(client, case_id, "business_approve_test_cases", BUSINESS)  # rows stay approved from cycle 1
    second = client.post(f"/api/onboardings/{case_id}/uat/runs", json={}, headers=TEAM).json()
    assert second["run"]["cycle"] == 2
    assert all(r["verdict"] == "PASS" for r in second["run"]["results"])
    _go(client, case_id, "ccre_accept_results", TEAM)

    kpis = client.get("/api/kpis", headers=PM).json()
    row = next(r for r in kpis["cases"] if r["id"] == case_id)
    assert row["cycles"] == 2
    assert kpis["summary"]["defects_found_by_ccre"] >= 1


def test_intake_by_chatbot_asks_every_m2c_column(client: TestClient) -> None:
    case_id = client.post("/api/onboardings", json={"ctry_cd": "BG", "title": "BG IOSS"},
                          headers=BUSINESS).json()["id"]
    first = client.post(f"/api/onboardings/{case_id}/intake/chat", headers=BUSINESS, json={
        "message": "BG consumer shipments must provide IOSS when SDT is present and no DD, "
                   "declared value above 150 EUR"}).json()
    assert not first["complete"]
    understood = first["criteria"]
    assert understood["shipment_type"] == "B2C" and understood["requirement_groups"] == ["IOSS"]
    assert understood["min_value"] == {"op": ">", "value": 150.0} and understood["currency"] == "EUR"
    assert first["missing"][0]["field"] == "region"
    # Each reply asks the next missing column and says what is accepted.
    asked = [first["missing"][0]["field"]]
    replies = [first]
    for answer in ["EU", "31-13-2026", "15-11-2026", "no expiry", "all products", "none", "none", "none"]:
        resp = client.post(f"/api/onboardings/{case_id}/intake/chat", json={"message": answer}, headers=BUSINESS)
        assert resp.status_code == 200, resp.text
        replies.append(resp.json())
        if replies[-1]["missing"]:
            asked.append(replies[-1]["missing"][0]["field"])
    assert asked[:4] == ["region", "effective_date", "effective_date", "expiry_date"]   # bad date asked again
    assert "Accepted:" in replies[1]["reply"]
    last = replies[-1]
    assert last["complete"], last["reply"]
    req = last["requirement"]
    assert req["mode"] == "CHAT"
    m2c = req["structured"]["m2c"]
    assert m2c["region"] == "EU" and m2c["effective_date"] == "2026-11-15" and m2c["expiry_date"] == "N/A"
    row = req["structured"]["m2c_row"]
    assert row["min_value"] == 150.01 and row["max_value"] is None      # '> 150' as the workbook writes it
    assert "matchCiMask" in row["other_logic"]
    overview = client.get(f"/api/onboardings/{case_id}", headers=BUSINESS).json()
    submit = next(a for a in overview["actions"] if a["name"] == "submit_requirement")
    assert submit["allowed"]


def test_ui_and_registry_are_served(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200 and "CCRE" in index.text
    for asset in ("app.js", "styles.css", "ccre.css"):
        assert client.get(f"/{asset}").status_code == 200
    registry = client.get("/api/agents").json()
    assert registry["llm_mode"] == "stub" and registry["available"] is True
    assert len(registry["agents"]) == 8
    meta = client.get("/api/lifecycle").json()
    assert [s["key"] for s in meta["stages"]][0] == "intake"
    assert len(meta["questions"]) >= 8


def test_internal_chat_with_the_orchestrator(client: TestClient) -> None:
    reply = client.post("/api/run", json={"message": "Package status for DE"}, headers=TEAM)
    assert reply.status_code == 200
    assert "country_package_status" in reply.json()["response"]
