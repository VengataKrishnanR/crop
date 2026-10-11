"""A mock CCRE requirement-evaluation endpoint, for offline UAT runs.

Behaves like CCRE in the ways the UAT loop depends on: a requirement group is
raised only when a rule in the M2C draft matches the shipment **and** the group
is mapped for the country in the config package. So a package gap shows up as a
failed test, exactly as it would in the real UAT environment.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from tools.core.models import CtryProcMapping, Rule, SirgDef

from .evaluator import EvaluationError, evaluate, facts_from_payload


def _in_band(value: Optional[float], low: Optional[float], high: Optional[float]) -> bool:
    if value is None:
        return low is None and high is None
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def _shipment_type_matches(rule_type: Optional[str], payload_type: Optional[str]) -> bool:
    if not rule_type:
        return True
    allowed = {t.strip().upper() for t in rule_type.split("/")}
    return (payload_type or "").upper() in allowed


def evaluate_shipment(session: Session, payload: dict[str, Any], rule_set_id: str) -> dict[str, Any]:
    """Return a CCRE-like response: which requirement groups were raised and why."""
    country = str(payload.get("destinationCountry") or "").upper()
    facts = facts_from_payload(payload)
    try:
        ship_date = dt.date.fromisoformat(str(payload.get("shipDate")))
    except ValueError:
        ship_date = dt.date.today()

    mapped = set(session.execute(
        select(SirgDef.cd).join(CtryProcMapping, CtryProcMapping.sirg_id == SirgDef.id)
        .where(CtryProcMapping.ctry_cd == country).distinct()
    ).scalars())

    rules = session.execute(
        select(Rule).where(Rule.rule_set_id == rule_set_id, Rule.ctry_cd == country)
        .options(selectinload(Rule.bindings)).order_by(Rule.row_no)
    ).scalars()

    raised: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    evaluated = 0
    for rule in rules:
        evaluated += 1
        label = f"rule {rule.row_no or rule.id[:8]} ({rule.sirg_cd})"
        if rule.effective_date and ship_date < rule.effective_date:
            continue
        if rule.expiry_date and ship_date > rule.expiry_date:
            continue
        if not _shipment_type_matches(rule.shipment_type, payload.get("shipmentType")):
            continue
        if not _in_band(_num(payload.get("declaredValue")), rule.min_value, rule.max_value):
            continue
        if not _in_band(_num(payload.get("weightKg")), rule.min_weight, rule.max_weight):
            continue
        try:
            if not evaluate(rule.other_logic or "", facts):
                continue
        except EvaluationError as exc:
            notes.append(f"{label}: condition not evaluable ({exc})")
            continue
        if rule.sirg_cd and rule.sirg_cd not in mapped:
            notes.append(f"{label} matched, but {rule.sirg_cd} is not mapped for {country} "
                         "in the config package — requirement not raised.")
            continue
        group = raised.setdefault(rule.sirg_cd or "?", {"group": rule.sirg_cd, "definitions": [],
                                                         "waivedToValidate": False})
        for b in rule.bindings:
            if b.cmpt_nm and b.cmpt_nm not in group["definitions"]:
                group["definitions"].append(b.cmpt_nm)
            group["waivedToValidate"] = group["waivedToValidate"] or bool(b.waived_to_validate)

    requirements = list(raised.values())
    return {
        "shipmentId": payload.get("shipmentId"),
        "destinationCountry": country,
        "caseCreated": bool(requirements),
        "requirements": requirements,
        "evaluatedRules": evaluated,
        "notes": notes,
        "engine": "mock-ccre",
    }


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
