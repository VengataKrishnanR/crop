"""Domain HTTP routes — mounted under ``/api`` by :mod:`server.app`.

Mounted for internal roles only (PM, CCRE consultant, CCRE team, admin); every
write additionally needs a CCRE role. Business users use the lifecycle routes.

The interface the platform's own UI talks to. Notice what is absent: there is no
endpoint that writes to CCRE, and no endpoint that advances a case past a gate
without the validator agreeing.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from tools.core import export as export_mod
from tools.core import grammar
from tools.workflow import state_machine as workflow
from tools.core.config import SETTINGS
from tools.core.db import get_session
from tools.core.models import (
    Approval, AuditEvent, ConfigPackage, CtryProcMapping, OnboardingCase, PermittedValue,
    ProposedChange, Rule, RuleBinding, RuleSet, SirAttribute, SirDef, SirgDef, ValidationRun,
)
from tools.validation import available_checks, load_snapshot, run_checks, validate_rule_set
from . import api_schemas as S
from .auth import require_ccre

router = APIRouter()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _statement(rule: Rule) -> str:
    """Render a rule as a sentence a reviewer can check against the requirement."""
    bits: list[str] = [f"For {rule.ctry_cd} {rule.direction.lower()} clearance"]
    if rule.shipment_type:
        bits.append(f"when the shipment is {rule.shipment_type}")
    if rule.min_value is not None or rule.max_value is not None:
        span = []
        if rule.min_value is not None:
            span.append(f"at least {rule.min_value:g}")
        if rule.max_value is not None:
            span.append(f"at most {rule.max_value:g}")
        bits.append(f"value is {' and '.join(span)} {rule.currency or ''}".strip())
    if rule.other_logic:
        bits.append(f"and the condition {rule.other_logic} holds")
    raised = [b.cmpt_nm or b.sirg_cd or "?" for b in rule.bindings]
    tail = (
        f"raise {rule.sirg_cd or 'a'} requirement"
        + (f" ({', '.join(raised)})" if raised else "")
    )
    waived = any(b.waived_to_validate for b in rule.bindings)
    if waived:
        tail += " and always create the case without validating it"
    return ", ".join(bits) + ", " + tail + "."


def _rule_out(rule: Rule) -> S.RuleOut:
    return S.RuleOut(
        id=rule.id, row_no=rule.row_no, direction=rule.direction, region=rule.region,
        ctry_cd=rule.ctry_cd, shipment_type=rule.shipment_type,
        effective_date=rule.effective_date, expiry_date=rule.expiry_date,
        network_product_codes=rule.network_product_codes, value_basis=rule.value_basis,
        currency=rule.currency, min_value=rule.min_value, max_value=rule.max_value,
        min_weight=rule.min_weight, max_weight=rule.max_weight, other_logic=rule.other_logic,
        country_hold_cd=rule.country_hold_cd, global_hold_cd=rule.global_hold_cd,
        sirg_cd=rule.sirg_cd, doc_reference=rule.doc_reference,
        generated_doc_reference=rule.generated_doc_reference,
        statement=_statement(rule),
        bindings=[
            S.BindingOut(
                id=b.id, sirg_cd=b.sirg_cd, sir_id=b.sir_id, cmpt_nm=b.cmpt_nm,
                waived_if_whitelisted=b.waived_if_whitelisted,
                waived_to_validate=b.waived_to_validate,
                check_service_code=b.check_service_code,
                attribute_ids=list(b.attribute_ids or []),
            )
            for b in rule.bindings
        ],
    )


def _get_case(session: Session, case_id: str) -> OnboardingCase:
    case = session.get(OnboardingCase, case_id)
    if case is None:
        raise HTTPException(404, f"no such case: {case_id}")
    return case


def _current_package(session: Session) -> Optional[str]:
    from tools.core.packages import active_package_version
    return active_package_version(session)


def _package_complete(session: Session, rule_set_id: str) -> bool:
    """True when the package covers every requirement the rule set references."""
    snapshot = load_snapshot(session, rule_set_id=rule_set_id)
    report = run_checks(snapshot, only=["CHK003", "CHK015", "CHK002"])
    return report.is_clean


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #

@router.get("/checks", tags=["meta"])
def checks() -> dict[str, str]:
    """The deterministic check register. This is the platform's authority, enumerated."""
    return available_checks()


# --------------------------------------------------------------------------- #
# ingestion
# --------------------------------------------------------------------------- #

@router.post("/ingest/package", tags=["ingest"], dependencies=[Depends(require_ccre)])
def ingest_package_endpoint(
    body: S.IngestRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from tools.ingestion.package import ingest_package

    try:
        result = ingest_package(session, body.path, body.version)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {
        "version": result.version, "source": result.source_name, "sirg": result.sirg,
        "sir": result.sir, "attributes": result.attributes, "mappings": result.mappings,
        "release_entries": result.release_entries, "unparseable": result.unparseable,
    }


@router.post("/ingest/workbook", tags=["ingest"], dependencies=[Depends(require_ccre)])
def ingest_workbook_endpoint(
    body: S.IngestRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    from tools.ingestion.workbook import ingest_workbook

    try:
        result = ingest_workbook(session, body.path, body.version, body.case_id)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return {
        "version": result.version, "source": result.source_name,
        "rule_set_id": result.rule_set_id, "rules": result.rules, "bindings": result.bindings,
        "mirror_sir": result.mirror_sir, "mirror_sirg": result.mirror_sirg,
        "unbound_rules": result.unbound_rules[:20],
        "orphan_bindings": result.orphan_bindings[:20],
    }


# --------------------------------------------------------------------------- #
# catalog
# --------------------------------------------------------------------------- #

@router.get("/catalog/groups", tags=["catalog"])
def catalog_groups(
    country: Optional[str] = Query(default=None), session: Session = Depends(get_session)
) -> dict[str, Any]:
    if country:
        stmt = (
            select(SirgDef.cd, SirgDef.nm, SirgDef.id)
            .join(CtryProcMapping, CtryProcMapping.sirg_id == SirgDef.id)
            .where(CtryProcMapping.ctry_cd == country.upper())
            .distinct()
        )
    else:
        stmt = select(SirgDef.cd, SirgDef.nm, SirgDef.id).distinct()
    rows = session.execute(stmt.order_by(SirgDef.cd)).all()
    return {"count": len(rows), "groups": [{"code": r[0], "name": r[1], "id": r[2]} for r in rows]}


@router.get("/catalog/definitions/{sir_id}", tags=["catalog"])
def catalog_definition(
    sir_id: str, package_version: Optional[str] = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    version = package_version or _current_package(session)
    sir = session.execute(
        select(SirDef).where(SirDef.id == sir_id, SirDef.package_version == version)
    ).scalar_one_or_none()
    if sir is None:
        raise HTTPException(404, f"no such requirement definition: {sir_id}")
    attributes = list(session.execute(
        select(SirAttribute)
        .where(SirAttribute.sir_id == sir_id, SirAttribute.package_version == version)
    ).scalars())
    active = session.execute(
        select(func.count()).select_from(CtryProcMapping)
        .where(CtryProcMapping.sir_id == sir_id, CtryProcMapping.package_version == version)
    ).scalar_one()
    return {
        "id": sir.id, "package_version": version, "name": sir.nm, "description": sir.dsc,
        "component": sir.cmpt_nm, "country": sir.ctry_cd, "derived_from": sir.derived_from_id,
        "sensitivity": sir.sensitivity,
        # No status field exists upstream, so activity is reachability.
        "active": active > 0,
        "mapping_count": active,
        "attributes": [
            {
                "id": a.att_id, "name": a.nm, "type": a.att_ty, "mandatory": a.is_mandatory,
                "path": a.ent_path, "message_positions": a.msg_positions,
            }
            for a in attributes
        ],
    }


@router.get("/catalog/countries/{country}/status", tags=["catalog"])
def country_status(country: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    code = country.upper()
    count = session.execute(
        select(func.count()).select_from(CtryProcMapping).where(CtryProcMapping.ctry_cd == code)
    ).scalar_one()
    groups = session.execute(
        select(SirgDef.cd)
        .join(CtryProcMapping, CtryProcMapping.sirg_id == SirgDef.id)
        .where(CtryProcMapping.ctry_cd == code)
        .distinct()
        .order_by(SirgDef.cd)
    ).scalars()
    return {
        "country": code, "in_package": count > 0, "mapping_rows": count,
        "configured_groups": list(groups),
    }


@router.get("/catalog/permitted", tags=["catalog"])
def permitted_values(session: Session = Depends(get_session)) -> dict[str, list[str]]:
    rows = session.execute(select(PermittedValue.field, PermittedValue.value)).all()
    out: dict[str, list[str]] = {}
    for field, value in rows:
        out.setdefault(field, []).append(value)
    return {k: sorted(set(v)) for k, v in out.items()}


# --------------------------------------------------------------------------- #
# cases and workflow
# --------------------------------------------------------------------------- #

@router.post("/cases", response_model=S.CaseOut, status_code=201, tags=["cases"])
def create_case(body: S.CaseCreate, session: Session = Depends(get_session)) -> OnboardingCase:
    existing = session.execute(
        select(OnboardingCase).where(OnboardingCase.code == body.code)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"case {body.code} already exists")
    case = OnboardingCase(**body.model_dump(), state=str(workflow.State.INTAKE))
    session.add(case)
    session.add(AuditEvent(case_id=case.id, actor="api", action="case:created", detail={"code": body.code}))
    session.commit()
    return case


@router.get("/cases", response_model=list[S.CaseOut], tags=["cases"])
def list_cases(
    state: Optional[str] = None, country: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[OnboardingCase]:
    stmt = select(OnboardingCase)
    if state:
        stmt = stmt.where(OnboardingCase.state == state.upper())
    if country:
        stmt = stmt.where(OnboardingCase.ctry_cd == country.upper())
    return list(session.execute(stmt.order_by(OnboardingCase.created_at.desc())).scalars())


@router.get("/cases/{case_id}", response_model=S.CaseOut, tags=["cases"])
def get_case(case_id: str, session: Session = Depends(get_session)) -> OnboardingCase:
    return _get_case(session, case_id)


@router.put("/cases/{case_id}/approved-rtp", tags=["cases"], dependencies=[Depends(require_ccre)])
def set_approved_rtp(
    case_id: str, body: S.ApprovedRtp, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Record the PM-approved production date.

    Separate from the requested date on purpose: reaching a date never releases
    anything, and the two values are both kept for the evidence pack.
    """
    case = _get_case(session, case_id)
    case.approved_rtp = body.approved_rtp
    session.add(AuditEvent(
        case_id=case.id, actor=body.actor, action="case:approved_rtp",
        detail={"approved_rtp": body.approved_rtp.isoformat(),
                "requested_rtp": case.requested_rtp.isoformat() if case.requested_rtp else None},
    ))
    session.commit()
    return {"case_id": case.id, "approved_rtp": case.approved_rtp}


@router.get("/cases/{case_id}/audit", tags=["workflow"])
def case_audit(case_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    _get_case(session, case_id)
    events = session.execute(
        select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.at)
    ).scalars()
    approvals = session.execute(
        select(Approval).where(Approval.case_id == case_id).order_by(Approval.at)
    ).scalars()
    return {
        "events": [
            {"at": e.at.isoformat(), "actor": e.actor, "action": e.action, "detail": e.detail}
            for e in events
        ],
        "approvals": [
            {
                "at": a.at.isoformat(), "stage": a.stage, "actor": a.actor, "role": a.role,
                "decision": a.decision, "comment": a.comment, "rule_set_version": a.rule_set_version,
            }
            for a in approvals
        ],
    }


# --------------------------------------------------------------------------- #
# rules
# --------------------------------------------------------------------------- #

@router.get("/rule-sets", tags=["rules"])
def list_rule_sets(
    case_id: Optional[str] = None, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    stmt = select(RuleSet)
    if case_id:
        stmt = stmt.where(RuleSet.case_id == case_id)
    sets = list(session.execute(stmt.order_by(RuleSet.created_at.desc())).scalars())
    return [
        {
            "id": rs.id, "version": rs.version, "label": rs.label, "sealed": rs.sealed,
            "case_id": rs.case_id, "created_at": rs.created_at.isoformat(),
            "rule_count": session.execute(
                select(func.count()).select_from(Rule).where(Rule.rule_set_id == rs.id)
            ).scalar_one(),
        }
        for rs in sets
    ]


@router.get("/rule-sets/{rule_set_id}/rules", response_model=list[S.RuleOut], tags=["rules"])
def list_rules(
    rule_set_id: str, country: Optional[str] = None, session: Session = Depends(get_session)
) -> list[S.RuleOut]:
    stmt = (
        select(Rule).where(Rule.rule_set_id == rule_set_id)
        .options(selectinload(Rule.bindings))
        .order_by(Rule.ctry_cd, Rule.row_no)
    )
    if country:
        stmt = stmt.where(Rule.ctry_cd == country.upper())
    return [_rule_out(r) for r in session.execute(stmt).scalars()]


@router.patch("/rules/{rule_id}", response_model=S.RuleOut, tags=["rules"], dependencies=[Depends(require_ccre)])
def update_rule(
    rule_id: str, body: S.RuleUpdate, session: Session = Depends(get_session)
) -> S.RuleOut:
    rule = session.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(404, f"no such rule: {rule_id}")
    rule_set = session.get(RuleSet, rule.rule_set_id)
    if rule_set is not None and rule_set.sealed:
        raise HTTPException(409, "rule set is sealed; fork a new version to change it")

    changes: dict[str, Any] = {}
    for field, value in body.model_dump(exclude_unset=True, exclude={"actor"}).items():
        before = getattr(rule, field)
        if before != value:
            changes[field] = {"from": str(before), "to": str(value)}
            setattr(rule, field, value)

    if changes:
        session.add(AuditEvent(
            case_id=rule_set.case_id if rule_set else None, actor=body.actor,
            action="rule:updated", detail={"rule_id": rule_id, "changes": changes},
        ))
    session.commit()
    session.refresh(rule)
    return _rule_out(rule)


@router.patch("/bindings/{binding_id}", tags=["rules"], dependencies=[Depends(require_ccre)])
def update_binding(
    binding_id: str, body: S.BindingUpdate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    binding = session.get(RuleBinding, binding_id)
    if binding is None:
        raise HTTPException(404, f"no such binding: {binding_id}")
    changes: dict[str, Any] = {}
    for field, value in body.model_dump(exclude_unset=True, exclude={"actor"}).items():
        before = getattr(binding, field)
        if before != value:
            changes[field] = {"from": str(before), "to": str(value)}
            setattr(binding, field, value)
    if changes:
        session.add(AuditEvent(
            actor=body.actor, action="binding:updated",
            detail={"binding_id": binding_id, "changes": changes},
        ))
    session.commit()
    return {"binding_id": binding_id, "changes": changes}


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #

@router.post("/rule-sets/{rule_set_id}/validate", response_model=S.ValidationOut, tags=["validation"])
def validate(
    rule_set_id: str, case_id: Optional[str] = None, persist: bool = True,
    session: Session = Depends(get_session),
) -> S.ValidationOut:
    if session.get(RuleSet, rule_set_id) is None:
        raise HTTPException(404, f"no such rule set: {rule_set_id}")
    report, run_id = validate_rule_set(session, rule_set_id, case_id=case_id, persist=persist)
    session.commit()
    payload = report.as_dict()
    payload["run_id"] = run_id
    return S.ValidationOut(**payload)


@router.post("/expressions/check", tags=["validation"])
def check_expression_endpoint(body: S.ExpressionCheck) -> dict[str, Any]:
    """Parse and check one expression. Used by the rule editor as you type."""
    diagnostics = grammar.analyse(body.expression)
    parses = not any(d.code == "EXPR_PARSE" for d in diagnostics)
    normalised: Optional[str] = None
    if parses:
        try:
            normalised = grammar.normalise(body.expression)
        except grammar.ExpressionError:
            parses = False
    return {
        "expression": body.expression,
        "parses": parses,
        "normalised": normalised,
        "errors": [d.message for d in diagnostics if d.severity == "error"],
        "warnings": [d.message for d in diagnostics if d.severity == "warning"],
        "service_codes": sorted(grammar.referenced_service_codes(body.expression)),
    }


@router.get("/validation-runs/{run_id}", tags=["validation"])
def get_validation_run(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(ValidationRun, run_id)
    if run is None:
        raise HTTPException(404, f"no such validation run: {run_id}")
    return {
        "id": run.id, "case_id": run.case_id, "rule_set_id": run.rule_set_id,
        "at": run.at.isoformat(), "blocker_count": run.blocker_count,
        "caution_count": run.caution_count, "info_count": run.info_count,
        "findings": run.findings,
    }


# --------------------------------------------------------------------------- #
# proposals (the advisory layer's only landing place)
# --------------------------------------------------------------------------- #

@router.get("/cases/{case_id}/proposals", response_model=list[S.ProposalOut], tags=["advisory"])
def list_proposals(case_id: str, session: Session = Depends(get_session)) -> list[ProposedChange]:
    _get_case(session, case_id)
    return list(session.execute(
        select(ProposedChange).where(ProposedChange.case_id == case_id)
        .order_by(ProposedChange.created_at.desc())
    ).scalars())


@router.post("/proposals/{proposal_id}/decide", tags=["advisory"], dependencies=[Depends(require_ccre)])
def decide_proposal(
    proposal_id: str, body: S.ProposalDecision, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Accept or reject a staged proposal.

    Accepting is the only way agent output becomes a rule, and it is a human
    action recorded against a named actor.
    """
    proposal = session.get(ProposedChange, proposal_id)
    if proposal is None:
        raise HTTPException(404, f"no such proposal: {proposal_id}")
    if proposal.status != "PROPOSED":
        raise HTTPException(409, f"proposal already {proposal.status}")

    if not body.accept:
        proposal.status = "REJECTED"
        session.add(AuditEvent(
            case_id=proposal.case_id, actor=body.actor, action="proposal:rejected",
            detail={"proposal_id": proposal_id, "comment": body.comment},
        ))
        session.commit()
        return {"proposal_id": proposal_id, "status": "REJECTED"}

    if not body.rule_set_id:
        raise HTTPException(400, "rule_set_id is required when accepting a proposal")
    rule_set = session.get(RuleSet, body.rule_set_id)
    if rule_set is None:
        raise HTTPException(404, f"no such rule set: {body.rule_set_id}")
    if rule_set.sealed:
        raise HTTPException(409, "rule set is sealed; fork a new version first")

    created: list[str] = []
    for proposed in (proposal.payload or {}).get("rules", []):
        rule = Rule(
            rule_set_id=rule_set.id,
            direction=proposed.get("direction") or "Import",
            region=proposed.get("region"),
            ctry_cd=proposed["ctry_cd"],
            shipment_type=proposed.get("shipment_type"),
            effective_date=_as_date(proposed.get("effective_date")),
            expiry_date=_as_date(proposed.get("expiry_date")),
            network_product_codes=proposed.get("network_product_codes"),
            value_basis=proposed.get("value_basis"),
            currency=proposed.get("currency"),
            min_value=proposed.get("min_value"),
            max_value=proposed.get("max_value"),
            min_weight=proposed.get("min_weight"),
            max_weight=proposed.get("max_weight"),
            other_logic=proposed.get("other_logic"),
            country_hold_cd=proposed.get("country_hold_cd"),
            global_hold_cd=proposed.get("global_hold_cd"),
            sirg_cd=proposed.get("sirg_cd"),
        )
        rule.doc_reference = rule.generated_doc_reference
        session.add(rule)
        session.flush()
        created.append(rule.id)
        if proposed.get("sir_id") or proposed.get("cmpt_nm"):
            session.add(RuleBinding(
                rule_id=rule.id, sirg_cd=proposed.get("sirg_cd"), sir_id=proposed.get("sir_id"),
                cmpt_nm=proposed.get("cmpt_nm"),
                waived_to_validate=bool(proposed.get("waived_to_validate")),
                waived_if_whitelisted=bool(proposed.get("waived_if_whitelisted")),
                attribute_ids=[],
            ))

    proposal.status = "ACCEPTED"
    session.add(AuditEvent(
        case_id=proposal.case_id, actor=body.actor, action="proposal:accepted",
        detail={"proposal_id": proposal_id, "rules_created": created, "comment": body.comment},
    ))
    session.flush()

    # Accepting a proposal does not approve it -- validate immediately so the
    # reviewer sees the consequences before anything else happens.
    report, run_id = validate_rule_set(session, rule_set.id, case_id=proposal.case_id, persist=True)
    proposal.validation_run_id = run_id
    session.commit()
    return {
        "proposal_id": proposal_id, "status": "ACCEPTED", "rules_created": created,
        "validation": report.as_dict(), "run_id": run_id,
    }


def _as_date(value: Any) -> Optional[dt.date]:
    if value in (None, ""):
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #

@router.get("/rule-sets/{rule_set_id}/export", tags=["export"])
def export_rule_set(rule_set_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Build the handover bundle.

    Support downloads this and uploads it to CCRE. The platform deliberately has
    no endpoint that performs that upload.
    """
    try:
        bundle = export_mod.build_export(session, rule_set_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "rule_set_id": bundle.rule_set_id,
        "version": bundle.rule_set_version,
        "files": {
            "Import.csv": bundle.import_csv(),
            "SIR-Reference.csv": bundle.sir_reference_csv(),
            "ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv": bundle.mapping_csv,
        },
        "evidence": bundle.evidence,
        "handover_note": (
            "Upload the package files to CCRE via the CCRE UI, then confirm the upload in the "
            "platform to complete the case."
        ),
    }


@router.post("/rule-sets/{rule_set_id}/seal", tags=["export"], dependencies=[Depends(require_ccre)])
def seal_rule_set(
    rule_set_id: str, actor: str = Query(...), session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        rule_set = export_mod.seal(session, rule_set_id, actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.add(AuditEvent(
        case_id=rule_set.case_id, actor=actor, action="rule_set:sealed",
        detail={"rule_set_id": rule_set_id, "version": rule_set.version},
    ))
    session.commit()
    return {"rule_set_id": rule_set_id, "version": rule_set.version, "sealed": True}


@router.post("/rule-sets/{rule_set_id}/fork", tags=["export"], dependencies=[Depends(require_ccre)])
def fork_rule_set(
    rule_set_id: str, version: str = Query(...), actor: str = Query(...),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Fork a rule set into a new version. Previous evidence is never overwritten."""
    try:
        clone = export_mod.fork(session, rule_set_id, version, actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.add(AuditEvent(
        case_id=clone.case_id, actor=actor, action="rule_set:forked",
        detail={"from": rule_set_id, "to": clone.id, "version": version},
    ))
    session.commit()
    return {"rule_set_id": clone.id, "version": clone.version, "forked_from": rule_set_id}
