"""Requirement gathering collects the M2C Import columns: read from text (NLP), checked
against what each field accepts, missing ones asked for, and turned into an M2C row."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import FULL_M2C
from test_v3_collab import BUSINESS, CONSULTANT, PM, TEAM, loaded  # noqa: F401
from tools import intake_fields as F

OPTIONS = {"country": "BG", "region": ["AM", "EU", "ME", "SB"], "region_default": "EU",
           "shipment_type": ["B2B", "B2C", "B2B/B2C"], "value_basis": ["DV", "IV"],
           "currency": ["EUR", "USD"], "currency_all": list(F.COMMON_CURRENCIES),
           "network_product_codes": ["H", "P", "Y"], "requirement_groups": ["POAB", "POA"],
           "min_ops": list(F.MIN_OPS), "max_ops": list(F.MAX_OPS)}


# --------------------------------------------------------------------------- #
# reading text
# --------------------------------------------------------------------------- #

def test_reads_every_column_from_a_sentence() -> None:
    c = F.extract("B2B and B2C shipments over €150 and up to 1000 EUR need POAB, weight between 2 and 30 kg, "
                  "network product codes P, Y, H, declared value, effective 2026-12-01 until 31-12-2027, "
                  "region EU, when the incoterm is DDP", OPTIONS)
    assert c["shipment_type"] == "B2B/B2C" and c["region"] == "EU"
    assert c["min_value"] == {"op": ">", "value": 150.0} and c["max_value"] == {"op": "<=", "value": 1000.0}
    assert c["min_weight"] == {"op": ">=", "value": 2.0} and c["max_weight"] == {"op": "<=", "value": 30.0}
    assert c["network_product_codes"] == ["P", "Y", "H"] and c["value_basis"] == "DV" and c["currency"] == "EUR"
    assert c["effective_date"] == "2026-12-01" and c["expiry_date"] == "2027-12-31"
    assert c["other_logic"] == 'incotermCodeList.contains("DDP")' and c["requirement_groups"] == ["POAB"]
    assert F.check(c, OPTIONS)["complete"]


def test_bg_ioss_sentence_gives_the_validated_logic() -> None:
    c = F.extract("BG consumer shipments must provide IOSS when SDT is present and no DD", OPTIONS)
    assert c["other_logic"] == 'matchCiMask("shortCode|==|SDT","value|!=|<blank>") && !serviceCodeList.contains("DD")'
    assert c["requirement_groups"] == ["IOSS"] and c["shipment_type"] == "B2C"


@pytest.mark.parametrize("text,side,expected", [
    ("> 150", "min", {"op": ">", "value": 150.0}), (">=150", "min", {"op": ">=", "value": 150.0}),
    ("over 150", "min", {"op": ">", "value": 150.0}), ("at least 50,5", "min", {"op": ">=", "value": 50.5}),
    ("150", "min", {"op": ">=", "value": 150.0}), ("< 1000", "max", {"op": "<", "value": 1000.0}),
    ("up to 1000 EUR", "max", {"op": "<=", "value": 1000.0}), ("= 22", "max", {"op": "=", "value": 22.0}),
    ("1000", "max", {"op": "<=", "value": 1000.0}), ("lots", "max", None),
])
def test_bound_operators(text: str, side: str, expected) -> None:
    assert F.parse_bound(text, side) == expected


def test_answers_to_questions() -> None:
    assert F.answer_for("expiry_date", "no expiry", OPTIONS) == F.NA
    assert F.answer_for("network_product_codes", "P, Y,8", OPTIONS) == ["P", "Y", "8"]
    assert F.answer_for("network_product_codes", "all products", OPTIONS) == F.NA
    assert F.answer_for("requirement_groups", "IOSS, POAB", OPTIONS) == ["IOSS", "POAB"]
    assert F.answer_for("region", "none", OPTIONS) is None            # required: 'none' is not an answer
    assert F.answer_for("other_logic", "only when the parcel is red", OPTIONS) == "only when the parcel is red"


# --------------------------------------------------------------------------- #
# checking and the M2C row
# --------------------------------------------------------------------------- #

def _full(**over):
    base = {**FULL_M2C, "requirement_groups": ["POAB"]}
    base.update(over)
    return F.check(base, OPTIONS)


def test_strict_bounds_become_the_workbooks_inclusive_numbers() -> None:
    res = _full(min_value={"op": ">", "value": 50}, max_value={"op": "<", "value": 1000},
                value_basis="IV", currency="EUR")
    assert res["complete"]
    assert res["m2c_row"]["min_value"] == 50.01 and res["m2c_row"]["max_value"] == 999.99
    eq = _full(min_weight={"op": "=", "value": 2}, max_weight=F.NA)
    assert eq["m2c_row"]["min_weight"] == eq["m2c_row"]["max_weight"] == 2.0


def test_what_is_not_accepted() -> None:
    assert "expiry_date" in _full(effective_date="2026-12-01", expiry_date="2026-11-01")["errors"]
    assert "max_value" in _full(min_value=">= 500", max_value="<= 100", value_basis="DV", currency="EUR")["errors"]
    assert "min_value" in _full(min_value={"op": "<", "value": 5})["errors"]          # wrong operator side
    assert "region" in _full(region="XX")["errors"]
    assert "network_product_codes" in _full(network_product_codes=["TOOLONG"])["errors"]
    res = _full(min_value=">= 150", currency="BGN", value_basis=F.NA)
    assert "value_basis" in res["errors"]                       # a value band needs DV/IV
    assert "currency" in res["warnings"]                         # BGN is not in the workbook list yet
    assert "other_logic" in _full(other_logic="only when red")["warnings"]   # plain words: CCRE converts


def test_missing_columns_become_questions_in_order() -> None:
    res = F.check({"requirement_groups": ["POAB"]}, OPTIONS)
    fields = [m["field"] for m in res["missing"]]
    assert fields[:3] == ["region", "shipment_type", "effective_date"]
    assert "value_basis" not in fields                          # only asked once a value limit is given
    assert "EU" in res["missing"][0]["question"]                 # hint from the country's existing rows
    with_value = F.check({"requirement_groups": ["POAB"], "min_value": "> 150"}, OPTIONS)
    assert {"value_basis", "currency"} <= {m["field"] for m in with_value["missing"]}


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #

def _case(client: TestClient, country: str = "BG") -> str:
    return client.post("/api/onboardings", json={"ctry_cd": country, "title": "t"}, headers=BUSINESS).json()["id"]


def test_fields_endpoint_lists_accepted_values(client: TestClient, loaded: None) -> None:
    case_id = _case(client)
    data = client.get(f"/api/onboardings/{case_id}/intake/fields", headers=BUSINESS).json()
    by_key = {f["key"]: f for f in data["fields"]}
    assert list(by_key)[:5] == ["region", "country", "shipment_type", "effective_date", "expiry_date"]
    assert "EU" in by_key["region"]["options"] and "P" in by_key["network_product_codes"]["options"]
    assert by_key["min_value"]["ops"] == [">=", ">", "="] and by_key["max_value"]["ops"] == ["<=", "<", "="]
    assert all(f["accepted"] for f in data["fields"])
    assert data["current"]["region"] == "EU" and data["current"]["country"] == "BG"


def test_nlp_extract_then_form_then_gate(client: TestClient) -> None:
    case_id = _case(client, "DE")
    nlp = client.post(f"/api/onboardings/{case_id}/intake/extract", headers=BUSINESS,
                      json={"text": "DE B2C shipments need POA above 150 EUR declared value"}).json()
    assert nlp["criteria"]["min_value"] == {"op": ">", "value": 150.0}
    assert {m["field"] for m in nlp["missing"]} >= {"region", "effective_date"}

    partial = client.post(f"/api/onboardings/{case_id}/intake/form", headers=BUSINESS, json={
        "description": "DE B2C shipments need POA above 150 EUR declared value", "m2c": {"region": "EU"}}).json()
    assert partial["check"]["complete"] is False
    submit = next(a for a in client.get(f"/api/onboardings/{case_id}", headers=BUSINESS).json()["actions"]
                  if a["name"] == "submit_requirement")
    assert not submit["allowed"] and "Effective Date" in submit["blocked_by"][0]

    full = client.post(f"/api/onboardings/{case_id}/intake/form", headers=BUSINESS, json={
        "description": "DE B2C shipments need POA above 150 EUR declared value",
        "m2c": {**FULL_M2C, "min_value": {"op": ">", "value": 150}, "max_value": "N/A"}}).json()
    assert full["check"]["complete"], full["check"]
    assert full["requirement"]["structured"]["m2c_row"]["min_value"] == 150.01
    assert client.post(f"/api/onboardings/{case_id}/transition", json={"name": "submit_requirement"},
                       headers=BUSINESS).status_code == 200


def test_rule_config_rows_from_the_requirement(client: TestClient, loaded: None) -> None:
    from test_v3_collab import _to_rule_config
    case_id = _to_rule_config(client, "DE")
    rows = client.post(f"/api/onboardings/{case_id}/rule-config/rows/from-requirement", headers=TEAM)
    assert rows.status_code == 200, rows.text
    row = rows.json()[0]
    assert row["sirg_cd"] == "POA" and row["region"] == "EU" and row["shipment_type"] == "B2C"
    assert row["effective_date"] == "2026-11-15" and row["row_no"] is None


# --------------------------------------------------------------------------- #
# the condition builder
# --------------------------------------------------------------------------- #

BASE = {**FULL_M2C, "requirement_groups": ["IOSS"]}


def test_builder_rows_become_m2c_columns() -> None:
    conds = [[{"field": "declared_value", "op": "gt", "value": 150, "currency": "EUR"}],
             [{"field": "weight", "op": "between", "value": 2, "value2": 30}],
             [{"field": "short_code", "op": "present", "values": ["SDT"]}],
             [{"field": "service_code", "op": "none", "values": ["DD"]},
              {"field": "incoterm", "op": "any", "values": ["DDP"]}]]
    res = F.check({**BASE, "conditions": conds}, OPTIONS)
    assert res["complete"], res
    row = res["m2c_row"]
    assert (row["min_value"], row["max_value"], row["value_basis"], row["currency"]) == (150.01, None, "DV", "EUR")
    assert (row["min_weight"], row["max_weight"]) == (2.0, 30.0)
    # Groups are joined with AND; rows inside a group with OR.
    assert row["other_logic"] == ('matchCiMask("shortCode|==|SDT","value|!=|<blank>") && '
                                  '(!serviceCodeList.contains("DD") || incotermCodeList.contains("DDP"))')


def test_no_conditions_means_nothing_else_applies() -> None:
    res = F.check({**BASE, "conditions": []}, OPTIONS)
    assert res["complete"]
    assert res["criteria"]["min_value"] == F.NA and res["m2c_row"]["other_logic"] is None


@pytest.mark.parametrize("conds,needle", [
    ([[{"field": "declared_value", "op": "gt", "value": 150, "currency": "EUR"},
       {"field": "weight", "op": "lt", "value": 3}]], "cannot be joined with OR"),
    ([[{"field": "declared_value", "op": "gt", "value": 150}]], "choose the currency"),
    ([[{"field": "declared_value", "op": "gt", "value": 1, "currency": "EUR"}],
      [{"field": "intrinsic_value", "op": "lt", "value": 9, "currency": "EUR"}]], "not both"),
    ([[{"field": "weight", "op": "between", "value": 30, "value2": 2}]], "not be below"),
    ([[{"field": "weight", "op": "gt", "value": "abc"}]], "enter a number"),
    ([[{"field": "service_code", "op": "any", "values": []}]], "choose a value"),
])
def test_builder_refuses_what_the_m2c_cannot_hold(conds, needle) -> None:
    res = F.check({**BASE, "conditions": conds}, OPTIONS)
    assert needle in res["errors"]["conditions"]
    assert not res["complete"]


def test_nlp_reading_is_offered_as_builder_rows(client: TestClient) -> None:
    case_id = _case(client)
    res = client.post(f"/api/onboardings/{case_id}/intake/extract", headers=BUSINESS, json={
        "text": "BG consumer shipments must provide IOSS when SDT is present and no DD, declared value above 150 EUR"}).json()
    fields = [g[0]["field"] for g in res["conditions"]]
    assert fields == ["declared_value", "short_code", "service_code"]
    assert res["conditions"][0][0] == {"field": "declared_value", "op": "gt", "value": 150.0, "currency": "EUR"}
    spec = client.get(f"/api/onboardings/{case_id}/intake/fields", headers=BUSINESS).json()["conditions"]
    assert {f["key"] for f in spec["fields"]} >= {"declared_value", "weight", "service_code", "incoterm", "short_code"}
    assert "DD" in spec["options"]["service_codes"] and "DDP" in spec["options"]["incoterms"]
    assert "CN" in spec["options"]["countries"]
