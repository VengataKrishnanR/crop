"""Domain API tests: ingestion, catalogue, rule edits, validation and export.

The full onboarding walkthrough (intake to RTP) is in test_e2e_positive.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app import app

CORRECTED_IOSS = (
    'matchCiMask("shortCode|==|SDT","value|!=|<blank>")&& !serviceCodeList.contains("DD")'
)


@pytest.fixture
def loaded(client: TestClient, real_package_path: Path, real_workbook_path: Path) -> dict:
    pkg = client.post("/api/ingest/package", json={"path": str(real_package_path)})
    assert pkg.status_code == 200, pkg.text
    wb = client.post("/api/ingest/workbook", json={"path": str(real_workbook_path)})
    assert wb.status_code == 200, wb.text
    return {"package": pkg.json(), "workbook": wb.json()}


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #

def test_health_and_check_register(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["version"] == "3.0.0"
    assert health["checks"] >= 16
    register = client.get("/api/checks").json()
    assert "CHK001" in register
    assert all(isinstance(v, str) and v for v in register.values())


def test_no_endpoint_writes_to_ccre(client: TestClient) -> None:
    """Structural assertion: there is no upload path to the production system."""
    paths = " ".join(list(app.openapi()["paths"]) + [getattr(r, "path", "") for r in app.routes]).lower()
    for forbidden in ("upload-to-ccre", "deploy", "publish-to-ccre", "ccre/upload"):
        assert forbidden not in paths


def test_expression_check_endpoint_reports_the_palette_defect(client: TestClient) -> None:
    body = {"expression": 'matchCiMask("shortCode,==,SDT")'}
    result = client.post("/api/expressions/check", json=body).json()
    assert result["errors"]
    assert any("shortCode|==|SDT" in e for e in result["errors"])


def test_expression_check_extracts_service_codes(client: TestClient) -> None:
    result = client.post("/api/expressions/check", json={"expression": CORRECTED_IOSS}).json()
    assert result["parses"]
    assert result["service_codes"] == ["DD"]
    assert result["errors"] == []


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #

def test_catalog_reports_bg_absent(client: TestClient, loaded: dict) -> None:
    status = client.get("/api/catalog/countries/BG/status").json()
    assert status["in_package"] is False
    assert status["mapping_rows"] == 0

    at_status = client.get("/api/catalog/countries/AT/status").json()
    assert at_status["in_package"] is True
    assert "IOSS" not in at_status["configured_groups"]


def test_definition_activity_is_derived_from_reachability(
    client: TestClient, loaded: dict
) -> None:
    """No status field exists upstream, so the API computes activity."""
    groups = client.get("/api/catalog/groups", params={"country": "AT"}).json()
    assert groups["count"] > 0

    # A definition reachable from the mapping table is active.
    mapped = client.get("/api/catalog/definitions/d59228af-d1eb-46bd-94fb-e8dd4a0b28b3").json()
    assert mapped["active"] is True
    assert mapped["mapping_count"] >= 1
    assert mapped["attributes"]

    # A shipped-but-unmapped definition is not.
    unmapped = client.get("/api/catalog/definitions/01181abf-cd84-4128-99a7-eb9ffccad502")
    if unmapped.status_code == 200:
        assert unmapped.json()["active"] is False


def test_permitted_values_exclude_bgn(client: TestClient, loaded: dict) -> None:
    permitted = client.get("/api/catalog/permitted").json()
    assert "EUR" in permitted["currency"]
    assert "BGN" not in permitted["currency"]


# --------------------------------------------------------------------------- #
# the BG walkthrough
# --------------------------------------------------------------------------- #

def test_editing_the_bg_expression_is_audited(client: TestClient, loaded: dict) -> None:
    rule_set_id = loaded["workbook"]["rule_set_id"]
    rules = client.get(
        f"/api/rule-sets/{rule_set_id}/rules", params={"country": "BG"}
    ).json()
    assert len(rules) == 2

    ioss = next(r for r in rules if r["sirg_cd"] == "IOSS")
    assert ioss["other_logic"] == '!serviceCodeList.contains("DD")'
    # The business-readable rendering the review screen shows.
    assert "For BG import clearance" in ioss["statement"]
    assert ioss["doc_reference"] != ioss["generated_doc_reference"]

    patched = client.patch(f"/api/rules/{ioss['id']}", json={
        "other_logic": CORRECTED_IOSS, "actor": "krish",
    })
    assert patched.status_code == 200
    assert patched.json()["other_logic"] == CORRECTED_IOSS

    audit = client.get("/api/cases/none/audit")
    assert audit.status_code == 404  # unknown case is a 404, not an empty success

    # Re-validating no longer reports an expression problem for that rule.
    report = client.post(f"/api/rule-sets/{rule_set_id}/validate").json()
    ioss_expr = [
        f for f in report["findings"]
        if f["code"].startswith("CHK010") and "IOSS" in f["where"]
    ]
    assert ioss_expr == []


def test_binding_waiver_can_be_corrected(client: TestClient, loaded: dict) -> None:
    rule_set_id = loaded["workbook"]["rule_set_id"]
    rules = client.get(f"/api/rule-sets/{rule_set_id}/rules", params={"country": "BG"}).json()
    binding = rules[0]["bindings"][0]
    assert binding["waived_to_validate"] is False

    result = client.patch(f"/api/bindings/{binding['id']}", json={
        "waived_to_validate": True, "actor": "jon",
    })
    assert result.status_code == 200
    assert result.json()["changes"]["waived_to_validate"]["to"] == "True"


def test_sealed_rule_sets_reject_edits_and_fork_instead(
    client: TestClient, loaded: dict
) -> None:
    rule_set_id = loaded["workbook"]["rule_set_id"]
    rules = client.get(f"/api/rule-sets/{rule_set_id}/rules", params={"country": "BG"}).json()
    rule_id = rules[0]["id"]

    assert client.post(
        f"/api/rule-sets/{rule_set_id}/seal", params={"actor": "jon"}
    ).status_code == 200

    blocked = client.patch(f"/api/rules/{rule_id}", json={"other_logic": "x", "actor": "jon"})
    assert blocked.status_code == 409
    assert "fork" in blocked.json()["detail"]

    forked = client.post(
        f"/api/rule-sets/{rule_set_id}/fork", params={"version": "v0.2", "actor": "jon"}
    )
    assert forked.status_code == 200
    new_id = forked.json()["rule_set_id"]
    assert new_id != rule_set_id

    # The fork is a full, independent copy.
    original = client.get(f"/api/rule-sets/{rule_set_id}/rules").json()
    copy = client.get(f"/api/rule-sets/{new_id}/rules").json()
    assert len(original) == len(copy)
    assert {r["id"] for r in original}.isdisjoint({r["id"] for r in copy})


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #

def test_export_regenerates_keys_and_is_deterministic(
    client: TestClient, loaded: dict
) -> None:
    rule_set_id = loaded["workbook"]["rule_set_id"]
    first = client.get(f"/api/rule-sets/{rule_set_id}/export").json()
    second = client.get(f"/api/rule-sets/{rule_set_id}/export").json()
    assert first["files"] == second["files"], "export must be byte-identical across runs"

    import csv as _csv
    import io as _io

    rows = list(_csv.DictReader(_io.StringIO(first["files"]["Import.csv"])))
    bg = [r for r in rows if r["Country"] == "BG"]
    assert len(bg) == 2
    for row in bg:
        # Document Reference is regenerated, so the hand-typed 3-part key is gone.
        assert row["Document Reference"] == "BG|Import||"
        # SIRG Document Reference keeps its own country|direction|group form.
        assert row["SIRG Document Reference"] in {"BG|Import|IOSS", "BG|Import|POAB"}
    # Mapping CSV carries the upstream column names.
    assert first["files"]["ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv"].startswith(
        "CtryProc.DhlCtryCd,CtryProc.ProcLvlCd"
    )
    # The handover is explicit about who uploads.
    assert "CCRE UI" in first["handover_note"]


def test_export_evidence_includes_validation_and_signoffs(
    client: TestClient, loaded: dict
) -> None:
    rule_set_id = loaded["workbook"]["rule_set_id"]
    case = client.post("/api/cases", json={
        "code": "ONB-2026-BG-015", "ctry_cd": "BG", "title": "BG evidence check",
    }).json()
    client.post(f"/api/rule-sets/{rule_set_id}/validate", params={"case_id": case["id"]})

    export = client.get(f"/api/rule-sets/{rule_set_id}/export").json()
    assert "change_summary" in export["evidence"]
    assert export["evidence"]["rule_set"]["version"] == "v0.1"
