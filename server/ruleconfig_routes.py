"""Rule configuration routes — edit the onboarding's M2C draft row by row.

Reading is open to internal users; editing is the CCRE team's, only while the
onboarding is in *Rule configuration + DMG* and the draft is not sealed. Every
edit is audited and answered with the row's fresh checks, so the screen always
shows what is wrong right where it was changed.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from tools import ruleconfig as rc
from tools.core.db import get_session
from tools.core.models import AuditEvent, OnboardingCase, Rule, RuleBinding, RuleSet, SirAttribute, SirDef
from tools.workflow import State
from tools.workflow.case_facts import baseline_rule_set, case_rule_set

from .auth import CurrentUser, ensure_country, require_ccre, require_internal

router = APIRouter(tags=["rule-config"])


# --------------------------------------------------------------------------- #
# request bodies
# --------------------------------------------------------------------------- #

class RowIn(BaseModel):
    region: Optional[str] = None
    shipment_type: Optional[str] = None
    effective_date: Optional[dt.date] = None
    expiry_date: Optional[dt.date] = None
    network_product_codes: Optional[str] = None
    value_basis: Optional[str] = None
    currency: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_weight: Optional[float] = None
    max_weight: Optional[float] = None
    other_logic: Optional[str] = None
    country_hold_cd: Optional[str] = None
    global_hold_cd: Optional[str] = None
    sirg_cd: Optional[str] = None


class BindingIn(BaseModel):
    sir_id: str = Field(min_length=1)
    sirg_cd: Optional[str] = None
    waived_if_whitelisted: bool = False
    waived_to_validate: bool = False
    check_service_code: Optional[str] = None
    attribute_ids: list[str] = Field(default_factory=list)


class ConditionIn(BaseModel):
    clauses: list[dict[str, Any]] = Field(default_factory=list)
    joiner: str = "and"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _case(session: Session, case_id: str, user: CurrentUser) -> OnboardingCase:
    case = session.get(OnboardingCase, case_id)
    if case is None:
        raise HTTPException(404, "No such onboarding.")
    ensure_country(user, case.ctry_cd)
    return case


def _draft(session: Session, case: OnboardingCase) -> RuleSet:
    rs = case_rule_set(session, case)
    if rs is None:
        raise HTTPException(409, "Start the M2C draft first.")
    return rs


def _editable(session: Session, case: OnboardingCase) -> RuleSet:
    if State(case.state) != State.RULE_CONFIG:
        raise HTTPException(409, "Rows can only be edited while the onboarding is in Rule configuration + DMG. "
                                 "If a correction is needed, reject back to rule configuration first.")
    rs = _draft(session, case)
    if rs.sealed:
        raise HTTPException(409, "This M2C draft is sealed.")
    return rs


def _row(session: Session, rs: RuleSet, case: OnboardingCase, rule_id: str) -> Rule:
    rule = session.get(Rule, rule_id)
    if rule is None or rule.rule_set_id != rs.id or rule.ctry_cd != case.ctry_cd:
        raise HTTPException(404, "No such row in this onboarding's M2C draft.")
    return rule


def _clean(v: Any) -> Any:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _apply(rule: Rule, body: RowIn) -> None:
    for field, value in body.model_dump(exclude_unset=True).items():
        value = _clean(value)
        if field in ("currency", "sirg_cd", "region", "value_basis", "country_hold_cd", "global_hold_cd") and value:
            value = value.upper()
        setattr(rule, field, value)


def _audit(session: Session, case: OnboardingCase, user: CurrentUser, action: str, detail: dict) -> None:
    session.add(AuditEvent(case_id=case.id, actor=user.label, action=action, detail=detail))


def _row_out(rule: Rule, cat: rc.Catalog, country: str) -> dict[str, Any]:
    issues = rc.row_issues(rule, cat, country)
    sir_names = {b.sir_id: (cat.defs[b.sir_id].nm if b.sir_id in cat.defs else None) for b in rule.bindings}
    return {
        "id": rule.id, "row_no": rule.row_no, **rc.rule_dict(rule),
        "document_reference": rule.generated_doc_reference,
        "sirg_document_reference": f"{rule.ctry_cd}|Import|{rule.sirg_cd or ''}",
        "bindings": [{
            "id": b.id, "sir_id": b.sir_id, "sir_name": sir_names.get(b.sir_id), "sirg_cd": b.sirg_cd,
            "cmpt_nm": b.cmpt_nm, "waived_if_whitelisted": b.waived_if_whitelisted,
            "waived_to_validate": b.waived_to_validate, "check_service_code": b.check_service_code,
            "attribute_ids": list(b.attribute_ids or []),
        } for b in rule.bindings],
        "issues": issues,
        "status": ("error" if any(i["level"] == "error" for i in issues)
                   else "package" if any(i["level"] == "package" for i in issues)
                   else "warning" if issues else "ok"),
    }


def _fresh(session: Session, rule: Rule, case: OnboardingCase) -> dict[str, Any]:
    session.commit()
    session.refresh(rule)
    return _row_out(rule, rc.Catalog.load(session, case.ctry_cd), case.ctry_cd)


# --------------------------------------------------------------------------- #
# the workspace
# --------------------------------------------------------------------------- #

@router.get("/onboardings/{case_id}/rule-config")
def workspace(case_id: str, user: CurrentUser = Depends(require_internal),
              session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rs = case_rule_set(session, case)
    cat = rc.Catalog.load(session, case.ctry_cd)
    editable = (State(case.state) == State.RULE_CONFIG and rs is not None and not rs.sealed
                and user.role.value in ("CCRE_TEAM", "CCRE_CONSULTANT", "ADMIN"))
    rows = [_row_out(r, cat, case.ctry_cd) for r in rc.draft_rows(session, rs, case.ctry_cd)] if rs else []
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "warning", "package", "error")}
    mapped_groups = sorted(cat.groups_by_id[g].cd for g in cat.mapped_groups if g in cat.groups_by_id)
    return {
        "country": case.ctry_cd,
        "draft": {"id": rs.id, "version": rs.version, "label": rs.label, "sealed": rs.sealed,
                  "source_version": rs.source_version} if rs else None,
        "package_version": cat.package_version,
        "editable": editable,
        "rows": rows,
        "summary": {"rows": len(rows), **counts},
        "options": {
            "permitted": {k: sorted(v) for k, v in cat.permitted.items()},
            "groups_mapped_for_country": mapped_groups,
            "all_groups": sorted(cat.groups_by_cd),
            "builder": rc.BUILDER_TYPES,
            "fields": rc.RULE_FIELDS,
        },
    }


# --------------------------------------------------------------------------- #
# rows (Import tab)
# --------------------------------------------------------------------------- #

@router.post("/onboardings/{case_id}/rule-config/rows")
def add_row(case_id: str, body: RowIn, user: CurrentUser = Depends(require_ccre),
            session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rs = _editable(session, case)
    rule = Rule(rule_set_id=rs.id, row_no=None, direction="Import", ctry_cd=case.ctry_cd)
    _apply(rule, body)
    session.add(rule)
    session.flush()
    _audit(session, case, user, "m2c:row_added", {"rule_id": rule.id, "sirg_cd": rule.sirg_cd})
    return _fresh(session, rule, case)


@router.put("/onboardings/{case_id}/rule-config/rows/{rule_id}")
def edit_row(case_id: str, rule_id: str, body: RowIn, user: CurrentUser = Depends(require_ccre),
             session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rule = _row(session, _editable(session, case), case, rule_id)
    before = rc.rule_dict(rule)
    _apply(rule, body)
    after = rc.rule_dict(rule)
    changed = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
    if changed:
        _audit(session, case, user, "m2c:row_edited", {"rule_id": rule.id, "row_no": rule.row_no, "changed": changed})
    return _fresh(session, rule, case)


@router.post("/onboardings/{case_id}/rule-config/rows/{rule_id}/duplicate")
def duplicate_row(case_id: str, rule_id: str, user: CurrentUser = Depends(require_ccre),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rs = _editable(session, case)
    src = _row(session, rs, case, rule_id)
    copy = Rule(rule_set_id=rs.id, row_no=None, direction=src.direction, ctry_cd=src.ctry_cd,
                **{f: getattr(src, f) for f in rc.RULE_FIELDS if f not in ("ctry_cd", "direction")})
    session.add(copy)
    session.flush()
    for b in src.bindings:
        session.add(RuleBinding(rule_id=copy.id, sirg_cd=b.sirg_cd, sirg_id=b.sirg_id, sir_id=b.sir_id,
                                cmpt_nm=b.cmpt_nm, waived_if_whitelisted=b.waived_if_whitelisted,
                                waived_to_validate=b.waived_to_validate, check_service_code=b.check_service_code,
                                attribute_ids=list(b.attribute_ids or [])))
    _audit(session, case, user, "m2c:row_duplicated", {"from": src.id, "rule_id": copy.id})
    return _fresh(session, copy, case)


@router.delete("/onboardings/{case_id}/rule-config/rows/{rule_id}")
def delete_row(case_id: str, rule_id: str, user: CurrentUser = Depends(require_ccre),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rule = _row(session, _editable(session, case), case, rule_id)
    _audit(session, case, user, "m2c:row_removed", {"rule_id": rule.id, "row_no": rule.row_no,
                                                    "row": rc.rule_dict(rule)})
    session.delete(rule)
    session.commit()
    return {"deleted": rule_id}


# --------------------------------------------------------------------------- #
# bindings (SIR Reference tab)
# --------------------------------------------------------------------------- #

def _binding_values(session: Session, body: BindingIn, rule: Rule, cat: rc.Catalog) -> dict[str, Any]:
    sir = cat.defs.get(body.sir_id.strip())
    group_cd = (_clean(body.sirg_cd) or rule.sirg_cd or "").upper() or None
    group = cat.groups_by_cd.get(group_cd or "")
    if body.attribute_ids and sir is not None:
        known = set(session.execute(select(SirAttribute.att_id).where(
            SirAttribute.sir_id == sir.id, SirAttribute.package_version == cat.package_version)).scalars())
        unknown = [a for a in body.attribute_ids if a not in known]
        if unknown:
            raise HTTPException(400, f"Attribute id(s) not in {sir.cmpt_nm or sir.nm}: {', '.join(unknown[:5])}.")
    return {"sir_id": body.sir_id.strip(), "sirg_cd": group_cd, "sirg_id": group.id if group else None,
            "cmpt_nm": sir.cmpt_nm if sir else None, "waived_if_whitelisted": body.waived_if_whitelisted,
            "waived_to_validate": body.waived_to_validate,
            "check_service_code": (_clean(body.check_service_code) or None),
            "attribute_ids": [a.strip() for a in body.attribute_ids if a.strip()]}


@router.post("/onboardings/{case_id}/rule-config/rows/{rule_id}/bindings")
def add_binding(case_id: str, rule_id: str, body: BindingIn, user: CurrentUser = Depends(require_ccre),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rule = _row(session, _editable(session, case), case, rule_id)
    values = _binding_values(session, body, rule, rc.Catalog.load(session, case.ctry_cd))
    if any(b.sir_id == values["sir_id"] for b in rule.bindings):
        raise HTTPException(409, "That requirement definition is already bound to this row.")
    session.add(RuleBinding(rule_id=rule.id, **values))
    _audit(session, case, user, "m2c:binding_added", {"rule_id": rule.id, "sir_id": values["sir_id"]})
    session.flush()
    session.refresh(rule)
    return _fresh(session, rule, case)


@router.put("/onboardings/{case_id}/rule-config/rows/{rule_id}/bindings/{binding_id}")
def edit_binding(case_id: str, rule_id: str, binding_id: str, body: BindingIn,
                 user: CurrentUser = Depends(require_ccre), session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rule = _row(session, _editable(session, case), case, rule_id)
    b = next((x for x in rule.bindings if x.id == binding_id), None)
    if b is None:
        raise HTTPException(404, "No such binding on this row.")
    for k, v in _binding_values(session, body, rule, rc.Catalog.load(session, case.ctry_cd)).items():
        setattr(b, k, v)
    _audit(session, case, user, "m2c:binding_edited", {"rule_id": rule.id, "binding_id": b.id})
    return _fresh(session, rule, case)


@router.delete("/onboardings/{case_id}/rule-config/rows/{rule_id}/bindings/{binding_id}")
def delete_binding(case_id: str, rule_id: str, binding_id: str, user: CurrentUser = Depends(require_ccre),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rule = _row(session, _editable(session, case), case, rule_id)
    b = next((x for x in rule.bindings if x.id == binding_id), None)
    if b is None:
        raise HTTPException(404, "No such binding on this row.")
    rule.bindings.remove(b)
    _audit(session, case, user, "m2c:binding_removed", {"rule_id": rule.id, "sir_id": b.sir_id})
    return _fresh(session, rule, case)


# --------------------------------------------------------------------------- #
# catalogue lookups
# --------------------------------------------------------------------------- #

@router.get("/onboardings/{case_id}/rule-config/definitions")
def search_definitions(case_id: str, q: str = "", group: str = "", user: CurrentUser = Depends(require_internal),
                       session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """Requirement definitions (SIRs) in the package — mapped for the country first."""
    case = _case(session, case_id, user)
    cat = rc.Catalog.load(session, case.ctry_cd)
    stmt = select(SirDef).where(SirDef.package_version == cat.package_version)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(SirDef.nm.ilike(like), SirDef.cmpt_nm.ilike(like), SirDef.id.ilike(like)))
    g = cat.groups_by_cd.get(group.strip().upper()) if group.strip() else None
    found = list(session.execute(stmt.limit(400)).scalars())
    if g is not None:
        # The group's own definitions for the country always come first, whatever the cap.
        ids = [sir for grp, sir in cat.mapped if grp == g.id]
        group_stmt = stmt.where(SirDef.id.in_(ids)) if ids else None
        if group_stmt is not None:
            have = {d.id for d in found}
            found = [d for d in session.execute(group_stmt).scalars() if d.id not in have] + found
    out = []
    for d in found:
        in_group = bool(g and (g.id, d.id) in cat.mapped)
        mapped_any = any(sir == d.id for _, sir in cat.mapped)
        out.append({"sir_id": d.id, "name": d.nm, "cmpt_nm": d.cmpt_nm, "country": d.ctry_cd,
                    "mapped_in_group": in_group, "mapped_for_country": mapped_any})
    out.sort(key=lambda x: (not x["mapped_in_group"], not x["mapped_for_country"], x["name"] or ""))
    return out[:60]


@router.get("/onboardings/{case_id}/rule-config/definitions/{sir_id}/attributes")
def definition_attributes(case_id: str, sir_id: str, user: CurrentUser = Depends(require_internal),
                          session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    case = _case(session, case_id, user)
    version = rc.current_package(session)
    rows = session.execute(select(SirAttribute).where(SirAttribute.sir_id == sir_id,
                                                      SirAttribute.package_version == version)
                           .order_by(SirAttribute.ent_path, SirAttribute.nm)).scalars()
    return [{"att_id": a.att_id, "name": a.nm, "path": a.ent_path, "type": a.att_ty, "mandatory": a.is_mandatory,
             "message_positions": [p.get("xPath") or p.get("jPath") for p in (a.msg_positions or [])
                                   if isinstance(p, dict)]} for a in rows]


@router.post("/onboardings/{case_id}/rule-config/condition")
def build_condition(case_id: str, body: ConditionIn, user: CurrentUser = Depends(require_internal),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    _case(session, case_id, user)
    try:
        return rc.build_expression(body.clauses, body.joiner)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/onboardings/{case_id}/rule-config/palette")
def condition_palette(case_id: str, user: CurrentUser = Depends(require_internal),
                      session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _case(session, case_id, user)
    return rc.palette(session)


# --------------------------------------------------------------------------- #
# changes, package coverage, M2C download
# --------------------------------------------------------------------------- #

@router.get("/onboardings/{case_id}/rule-config/changes")
def draft_changes(case_id: str, user: CurrentUser = Depends(require_internal),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rs = _draft(session, case)
    base = baseline_rule_set(session, case.ctry_cd)
    items = rc.changes(session, rs, base, case.ctry_cd)
    return {"baseline": base.source_version if base else None, "items": items,
            "counts": {s: sum(1 for i in items if i["status"] == s) for s in ("NEW", "CHANGED", "REMOVED", "UNCHANGED")},
            "labels": rc.RULE_FIELDS}


@router.get("/onboardings/{case_id}/rule-config/coverage")
def package_coverage(case_id: str, user: CurrentUser = Depends(require_internal),
                     session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rs = _draft(session, case)
    cat = rc.Catalog.load(session, case.ctry_cd)
    return rc.coverage(session, rc.draft_rows(session, rs, case.ctry_cd), cat, case.ctry_cd)


@router.get("/onboardings/{case_id}/rule-config/coverage.csv")
def package_request_csv(case_id: str, user: CurrentUser = Depends(require_internal),
                        session: Session = Depends(get_session)) -> Response:
    """The Support request: country mapping rows the config package must add."""
    data = package_coverage(case_id, user, session)
    buf = io.StringIO()
    cols = ["CtryProc.DhlCtryCd", "CtryProc.ProcLvlCd", "ShpInfReqGrpDef.Cd", "ShpInfReqGrpDef.Id",
            "ShpInfReqDef.Id", "ShpInfReqDef.CmptNm", "Needed"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(data["support_request"])
    case = session.get(OnboardingCase, case_id)
    return Response(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{case.code}_package_request.csv"'})


@router.get("/onboardings/{case_id}/rule-config/m2c.xlsx")
def m2c_workbook(case_id: str, user: CurrentUser = Depends(require_internal),
                 session: Session = Depends(get_session)) -> Response:
    case = _case(session, case_id, user)
    rs = _draft(session, case)
    items = rc.changes(session, rs, baseline_rule_set(session, case.ctry_cd), case.ctry_cd)
    body = rc.build_m2c_workbook(session, case, rs, items)
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{case.code}_M2C_{rs.version}.xlsx"'})
