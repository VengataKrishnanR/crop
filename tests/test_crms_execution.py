"""The onboarded CRMS API test suite: admin endpoints, CRMS payloads, execution,
environment comparison and review downloads.

The endpoint is simulated with an httpx MockTransport that behaves like the CRMS
categorization service (response shape taken from the suite's saved outputs).
The sample request is synthetic but has the real ``ShpPcdDetailsMsg`` structure.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from tools.execution.checker import check_response
from tools.execution.crms import build_crms_payload, compare_responses, find_differences

pytestmark = pytest.mark.integration

BUSINESS = {"X-CCRE-Role": "BUSINESS"}
TEAM = {"X-CCRE-Role": "CCRE_TEAM"}
CONSULTANT = {"X-CCRE-Role": "CCRE_CONSULTANT"}
PM = {"X-CCRE-Role": "PM"}

SECRET = "test-key-not-real-0001"
CRMS_PATHS = {
    "groups_path": "MvmtMsg.Bd.Mvmt[].PcsInMvmt[].RqrReglDecTy[].TyCd", "case_flag_path": "",
    "status_path": "MvmtMsg.RespStatus[].Sev", "status_ok_value": "10", "compare_path": "MvmtMsg.Bd",
}

SAMPLE = {"ShpPcdDetailsMsg": {
    "Hdr": {"@Dtm": "2026-01-01T00:00:00Z", "Sndr": {"@AppCd": "TEST"}},
    "Bd": {
        "GenReq": [{"GenrcRqCritr": [{"@CompOp": "", "@TyCd": "CtryCd", "Val": ["SE"]},
                                     {"@CompOp": "", "@TyCd": "ProcTy", "Val": ["Export"]},
                                     {"@TyCd": "TrgGSSFlg", "Val": ["N"]}], "GenrcRqObj": []}],
        "Shp": [{
            "DstCtryCd": "NO", "OrgCtryCd": "IE", "DstSrvACd": "BGO",
            "Srv": [{"GlSrvCd": {"$": "PS", "@GlProdSrvClssCd": "S"}},
                    {"GlSrvCd": {"$": "DS", "@GlProdSrvClssCd": "S"}}],
            "DatElGrp": [{"@Cd": "ShpClss", "DatEl": [{"Cd": "ClssTy", "Val": {"$": "ShpTrTyClss"}},
                                                      {"Cd": "Clss", "Val": {"$": "B2B"}}]}],
            "MonAmt": [{"@TyCd": "SCUSV", "Amt": [{"$": 199.0, "@CurCd": "EUR"}]}],
            "ShpDoc": [{"CmrcInv": {"IncTrmCd": "DAP",
                                    "MonAmt": [{"@TyCd": "TINVA", "Amt": [{"$": 1200, "@CurCd": "EUR"}]}]}}],
            "ShpRef": [{"@TyCd": "UCI", "Ref": "ORIGINAL"}],
        }],
    },
}}


def _crms_response(payload: dict, env: str) -> dict:
    """What the categorization service returns: POA declaration for DDP, '-' otherwise."""
    shp = payload["ShpPcdDetailsMsg"]["Bd"]["Shp"][0]
    ddp = shp["ShpDoc"][0]["CmrcInv"]["IncTrmCd"] == "DDP"
    decl = "POA" if ddp else "-"
    body = {"MvmtMsg": {
        "Hdr": {"@Dtm": f"2026-01-23T05:45:1{len(env)}Z", "@Id": f"id-{env}"},
        "Bd": {"Mvmt": [{"PcsInMvmt": [{"PcsId": "PID1", "RqrReglDecTy": [{"TyCd": decl}]}]}]},
        "RespStatus": [{"Sev": 10, "Dsc": "Service operation execution finished successfully."}],
    }}
    if env == "uat" and ddp:  # the UAT environment behaves differently for one case
        body["MvmtMsg"]["Bd"]["Mvmt"][0]["PcsInMvmt"][0]["RqrReglDecTy"][0]["TyCd"] = "IOSS"
    return body


@pytest.fixture
def crms_transport(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("x-api-key") != SECRET:
            return httpx.Response(401, json={"error": "invalid api key"})
        env = "uat" if "uat" in request.url.host else "test"
        return httpx.Response(200, json=_crms_response(json.loads(request.content), env))

    import tools.execution.executor as executor

    monkeypatch.setattr(executor, "_TRANSPORT", httpx.MockTransport(handler))
    return calls


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #

def test_crms_payload_follows_the_test_case() -> None:
    case = {"test_id": "DE-POA-01P", "input_conditions": [
        {"field": "incoterm", "operator": "equals", "value": "DDP"},
        {"field": "shipment_type", "operator": "equals", "value": "B2C"},
        {"field": "service_code", "operator": "not_contains", "value": "DS"},
        {"field": "declared_value", "operator": "equals", "value": 250}]}
    out = build_crms_payload(SAMPLE, case, "DE")
    bd = out["payload"]["ShpPcdDetailsMsg"]["Bd"]
    shp = bd["Shp"][0]
    assert bd["GenReq"][0]["GenrcRqCritr"][0]["Val"] == ["DE"]
    assert bd["GenReq"][0]["GenrcRqCritr"][1]["Val"] == ["Import"]
    assert shp["DstCtryCd"] == "DE" and shp["ShpDoc"][0]["CmrcInv"]["IncTrmCd"] == "DDP"
    assert [s["GlSrvCd"]["$"] for s in shp["Srv"]] == ["PS"]
    assert shp["DatElGrp"][0]["DatEl"][1]["Val"] == {"$": "B2C"}
    assert shp["MonAmt"][0]["Amt"][0]["$"] == 250.0
    assert shp["ShpRef"][0]["Ref"] == "UAT-DE-POA-01P"
    assert SAMPLE["ShpPcdDetailsMsg"]["Bd"]["Shp"][0]["DstCtryCd"] == "NO", "the sample must not be mutated"


def test_unmapped_conditions_are_reported_not_invented() -> None:
    out = build_crms_payload(SAMPLE, {"input_conditions": [{"field": "SDT", "operator": "present"}]}, "DE")
    assert out["assumptions"] and "SDT" in out["assumptions"][0]


def test_comparison_ignores_headers_like_the_suite() -> None:
    a, b = _crms_response(build_crms_payload(SAMPLE, {}, "DE")["payload"], "test"), \
        _crms_response(build_crms_payload(SAMPLE, {}, "DE")["payload"], "uat")
    assert compare_responses(a, b)["identical"] is True
    a2 = json.loads(json.dumps(a))
    a2["MvmtMsg"]["Bd"]["Mvmt"][0]["PcsInMvmt"][0]["RqrReglDecTy"][0]["TyCd"] = "X"
    diff = compare_responses(a2, b, "MvmtMsg.Bd")
    assert diff["identical"] is False and diff["summary"]["modified"] == 1
    assert find_differences({"a": 1}, {"b": 1}) == [
        {"path": "a", "type": "removed", "value1": 1}, {"path": "b", "type": "added", "value2": 1}]


def test_checker_reads_the_crms_response() -> None:
    body = _crms_response(build_crms_payload(SAMPLE, {}, "DE")["payload"], "test")
    paths = {k: v for k, v in CRMS_PATHS.items() if k != "compare_path"}
    paths = {"groups_path": paths["groups_path"], "case_path": "", "status_path": paths["status_path"],
             "status_ok": paths["status_ok_value"]}
    assert check_response(body, 200, "POA", False, **paths)["passed"] is True  # '-' means nothing raised
    assert check_response(body, 200, "POA", True, **paths)["passed"] is False
    body["MvmtMsg"]["RespStatus"][0]["Sev"] = 40
    failed = check_response(body, 200, None, False, **paths)
    assert failed["passed"] is False and "did not report success" in failed["reasons"][0]


# --------------------------------------------------------------------------- #
# admin endpoints
# --------------------------------------------------------------------------- #

def _endpoint(client: TestClient, name: str, url: str, secret: str = SECRET) -> dict:
    resp = client.post("/api/admin/endpoints", json={"name": name, "url": url, "secret": secret, **CRMS_PATHS})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_credentials_are_encrypted_and_never_returned(client: TestClient) -> None:
    ep = _endpoint(client, "CRMS TEST", "https://crms-test.example.dhl.com/categorization")
    assert ep["secret_set"] and ep["secret_hint"].endswith("0001")
    assert SECRET not in json.dumps(client.get("/api/admin/endpoints").json())

    from server.app import app
    from tools.core.db import get_session
    from tools.core.models import ExecutionEndpoint

    session = next(app.dependency_overrides[get_session]())
    stored = session.get(ExecutionEndpoint, ep["id"])
    assert stored.secret_enc and SECRET not in stored.secret_enc

    # Keeping, replacing and clearing the credential
    kept = client.patch(f"/api/admin/endpoints/{ep['id']}", json={"timeout_seconds": 10}).json()
    assert kept["secret_set"] and kept["timeout_seconds"] == 10
    cleared = client.patch(f"/api/admin/endpoints/{ep['id']}", json={"clear_secret": True}).json()
    assert cleared["secret_set"] is False


def test_endpoint_validation(client: TestClient) -> None:
    bad_url = client.post("/api/admin/endpoints", json={"name": "x", "url": "ftp://nope.example"})
    assert bad_url.status_code == 400
    key_in_headers = client.post("/api/admin/endpoints", json={
        "name": "x", "url": "https://a.example.com", "extra_headers": {"x-api-key": "plain"}})
    assert key_in_headers.status_code == 400 and "encrypted" in key_in_headers.json()["detail"]
    _endpoint(client, "DUP", "https://a.example.com")
    assert client.post("/api/admin/endpoints", json={"name": "DUP", "url": "https://b.example.com"}).status_code == 409


def test_only_admin_configures_and_ccre_sees_names_only(client: TestClient) -> None:
    _endpoint(client, "CRMS UAT", "https://crms-uat.example.dhl.com/categorization")
    assert client.get("/api/admin/endpoints", headers=TEAM).status_code == 403
    assert client.post("/api/admin/endpoints", headers=TEAM,
                       json={"name": "x", "url": "https://x.example.com"}).status_code == 403
    targets = client.get("/api/uat/endpoints", headers=TEAM).json()
    assert targets == [{"id": targets[0]["id"], "name": "CRMS UAT", "comparable": True}]
    assert client.get("/api/uat/endpoints", headers=BUSINESS).status_code == 403


def test_admin_test_connection(client: TestClient, crms_transport) -> None:
    ep = _endpoint(client, "CRMS TEST", "https://crms-test.example.dhl.com/categorization")
    tpl = client.post("/api/uat/templates", json={"name": "CRMS sample", "body": SAMPLE}, headers=TEAM).json()
    result = client.post(f"/api/admin/endpoints/{ep['id']}/test", json={"template_id": tpl["id"]}).json()
    assert result["reachable"] and result["status"] == 200 and result["response_readable"]
    assert crms_transport[-1].headers["x-api-key"] == SECRET

    wrong = _endpoint(client, "WRONG KEY", "https://crms-test.example.dhl.com/categorization", secret="nope")
    denied = client.post(f"/api/admin/endpoints/{wrong['id']}/test", json={"template_id": tpl["id"]}).json()
    assert denied["status"] == 401 and not denied["response_readable"]


# --------------------------------------------------------------------------- #
# full UAT run against the endpoint, with comparison and downloads
# --------------------------------------------------------------------------- #

@pytest.fixture
def loaded(client: TestClient, real_package_path: Path, real_workbook_path: Path) -> None:
    assert client.post("/api/ingest/package", json={"path": str(real_package_path)}).status_code == 200
    assert client.post("/api/ingest/workbook", json={"path": str(real_workbook_path)}).status_code == 200


def test_uat_run_against_crms_with_comparison_and_downloads(
        client: TestClient, loaded: None, crms_transport) -> None:
    from test_e2e_positive import _onboard_to_uat_execution

    test_ep = _endpoint(client, "CRMS TEST", "https://crms-test.example.dhl.com/categorization")
    uat_ep = _endpoint(client, "CRMS UAT", "https://crms-uat.example.dhl.com/categorization")
    tpl = client.post("/api/uat/templates", json={"name": "CRMS sample", "country": "DE", "body": SAMPLE},
                      headers=TEAM).json()
    case_id = _onboard_to_uat_execution(client)

    run = client.post(f"/api/onboardings/{case_id}/uat/runs", headers=TEAM, json={
        "template_id": tpl["id"], "endpoint_id": test_ep["id"], "compare_endpoint_id": uat_ep["id"]})
    assert run.status_code == 200, run.text
    body = run.json()["run"]
    assert body["executor"] == "CRMS TEST vs CRMS UAT"
    results = {r["test_id"]: r for r in body["results"]}
    assert all(r["verdict"] == "PASS" for r in results.values()), results
    positive = next(r for k, r in results.items() if k.endswith("P"))
    negative = next(r for k, r in results.items() if k.endswith("N"))
    # UAT answers IOSS where TEST answers POA → the comparison flags it; '-' answers are identical.
    assert positive["comparison"]["identical"] is False and positive["comparison"]["differences"] == 1
    assert negative["comparison"]["identical"] is True

    sent = [json.loads(c.content) for c in crms_transport]
    assert all("ShpPcdDetailsMsg" in p for p in sent)
    assert {p["ShpPcdDetailsMsg"]["Bd"]["Shp"][0]["DstCtryCd"] for p in sent} == {"DE"}

    # Per-test downloads: the exact request and response
    req = client.get(f"/api/uat/results/{positive['id']}/download?part=request", headers=TEAM)
    assert req.status_code == 200 and "attachment" in req.headers["content-disposition"]
    assert req.json()["ShpPcdDetailsMsg"]["Bd"]["Shp"][0]["ShpDoc"][0]["CmrcInv"]["IncTrmCd"] == "DDP"
    resp = client.get(f"/api/uat/results/{positive['id']}/download?part=response", headers=TEAM)
    assert resp.json()["MvmtMsg"]["RespStatus"][0]["Sev"] == 10
    cmp_ = client.get(f"/api/uat/results/{positive['id']}/download?part=compare", headers=TEAM).json()
    assert cmp_["endpoint"] == "CRMS UAT" and cmp_["identical"] is False

    # Whole-run zip with the Excel summary
    zipped = client.get(f"/api/uat/runs/{body['id']}/download", headers=TEAM)
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(zipped.content)).namelist()
    assert "summary.xlsx" in names
    assert any(n.startswith("requests/") for n in names) and any(n.startswith("responses/") for n in names)
    assert any(n.endswith("_differences.json") for n in names)

    # The credential never appears in anything a reviewer can download
    assert SECRET not in zipped.content.decode("latin-1")

    # Business cannot download before the CCRE team has accepted the results …
    assert client.get(f"/api/uat/runs/{body['id']}/download", headers=BUSINESS).status_code == 404
    client.post(f"/api/onboardings/{case_id}/transition", json={"name": "ccre_accept_results"}, headers=TEAM)
    # … and can afterwards, for their review and sign-off.
    assert client.get(f"/api/uat/runs/{body['id']}/download", headers=BUSINESS).status_code == 200


def test_unreachable_endpoint_is_an_error_result(client: TestClient, loaded: None, monkeypatch) -> None:
    from test_e2e_positive import _onboard_to_uat_execution
    import tools.execution.executor as executor

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(executor, "_TRANSPORT", httpx.MockTransport(refuse))
    ep = _endpoint(client, "DOWN", "https://down.example.com/x")
    case_id = _onboard_to_uat_execution(client)
    run = client.post(f"/api/onboardings/{case_id}/uat/runs", headers=TEAM, json={"endpoint_id": ep["id"]}).json()
    assert all(r["verdict"] == "ERROR" for r in run["run"]["results"])
    assert run["state"] == "UAT_RESULT_REVIEW"
    blocked = client.post(f"/api/onboardings/{case_id}/transition", json={"name": "ccre_accept_results"},
                          headers=TEAM)
    assert blocked.status_code == 409
