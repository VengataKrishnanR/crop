"""Lifecycle routes — one onboarding from intake to RTP, role by role.

Every endpoint checks three things before acting: the caller's role, that the
caller may see the case's country (business users are scoped), and that the
case is in a state where the action makes sense. Transitions are fired with the
caller's *own* role — never a role the caller claims.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from tools.core.db import get_session
from tools.core.models import (
    AuditEvent, ExecutionEndpoint, Milestone, OnboardingCase, PayloadTemplate, ProposedChange, Requirement,
    Rule, Timeline, UatComparison, UatResult, UatRun, UatTestCase,
)
from tools.core.security import CCRE_ROLES, UserRole
from tools import intake_fields as F
from tools.execution import builtin_sample_payload
from tools.timeline import (
    MILESTONES, QUESTIONS, complexity_facts, estimate, normalise_answers, validate_plan,
)
from tools.validation import validate_rule_set
from tools.workflow import (
    STAGES, STATE_LABELS, TRANSITIONS, Role, State, TransitionError, can_fire, find_transition, fire,
    stage_of, transitions_from,
)
from tools.workflow.case_facts import (
    case_rule_set, correction_cycle, current_timeline, executable_test_cases, gate_context,
    latest_requirement, latest_run, start_m2c_draft,
)

from . import api_schemas as S
from .advisory import AdvisoryService, AdvisoryUnavailable
from .agent_invoker import AgentInvocationError
from .auth import CurrentUser, current_user, ensure_country, require, require_ccre, require_internal

router = APIRouter()
advisory = AdvisoryService()

_INTAKE_ROLES = (UserRole.BUSINESS, UserRole.CCRE_TEAM, UserRole.CCRE_CONSULTANT, UserRole.ADMIN)
# The PM owns the timeline: answers, plans, edits and approves it. Everyone internal can view it.
_TIMELINE_ROLES = (UserRole.PM, UserRole.ADMIN)

# Which timeline milestone each state belongs to (for recording actual dates).
_STATE_MILESTONE = {
    State.RULE_CONFIG: "RULE_CONFIG_DMG",
    State.SANITY_CHECK: "SANITY_CHECK",
    State.UAT_TC_PREP: "UAT_TC_PREP",
    State.UAT_TC_REVIEW_CCRE: "UAT_TC_REVIEW",
    State.UAT_TC_REVIEW_BUSINESS: "UAT_TC_REVIEW",
    State.UAT_EXECUTION: "UAT_EXECUTION",
    State.UAT_RESULT_REVIEW: "UAT_REVIEW_SIGNOFF",
    State.UAT_SIGNOFF: "UAT_REVIEW_SIGNOFF",
    State.RTP: "RTP",
}
_MILESTONE_ORDER = [m["stage"] for m in MILESTONES]

# What business users may see, by state.
_BUSINESS_SEES_TESTS = {State.UAT_TC_REVIEW_BUSINESS, State.UAT_EXECUTION, State.UAT_RESULT_REVIEW,
                        State.UAT_SIGNOFF, State.RTP, State.COMPLETED}
_BUSINESS_SEES_RESULTS = {State.UAT_SIGNOFF, State.RTP, State.COMPLETED}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _today() -> dt.date:
    return dt.date.today()


def _case(session: Session, case_id: str, user: CurrentUser) -> OnboardingCase:
    case = session.get(OnboardingCase, case_id)
    if case is None:
        raise HTTPException(404, "No such onboarding.")
    ensure_country(user, case.ctry_cd)
    return case


def _require_state(case: OnboardingCase, *states: State) -> None:
    if State(case.state) not in states:
        wanted = ", ".join(STATE_LABELS[s] for s in states)
        raise HTTPException(409, f"Not possible now: the onboarding is '{STATE_LABELS[State(case.state)]}'. "
                                 f"This needs: {wanted}.")


def _advise(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AdvisoryUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except AgentInvocationError as exc:
        raise HTTPException(502, f"Agent failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _audit(session: Session, case_id: Optional[str], actor: str, action: str, detail: dict) -> None:
    session.add(AuditEvent(case_id=case_id, actor=actor, action=action, detail=detail))


def _requirement_out(req: Optional[Requirement]) -> Optional[dict[str, Any]]:
    if req is None:
        return None
    return {"id": req.id, "version": req.version, "mode": req.mode, "text": req.text,
            "structured": req.structured, "created_by": req.created_by,
            "created_at": req.created_at.isoformat() if req.created_at else None}


def _timeline_out(tl: Optional[Timeline]) -> Optional[dict[str, Any]]:
    if tl is None:
        return None
    return {
        "id": tl.id, "version": tl.version, "status": tl.status, "at_risk": tl.at_risk,
        "assumptions": tl.assumptions, "risks": tl.risks, "open_questions": tl.open_questions,
        "answers": tl.answers, "facts": tl.facts, "created_by": tl.created_by,
        "approved_by": tl.approved_by,
        "approved_at": tl.approved_at.isoformat() if tl.approved_at else None,
        "milestones": [
            {"stage": m.stage, "name": m.name, "owner": m.owner,
             "start": m.planned_start.isoformat(), "end": m.planned_end.isoformat(),
             "actual_start": m.actual_start.isoformat() if m.actual_start else None,
             "actual_end": m.actual_end.isoformat() if m.actual_end else None,
             "notes": m.notes}
            for m in tl.milestones
        ],
    }


def _test_case_out(tc: UatTestCase, business: bool) -> dict[str, Any]:
    base = {"id": tc.id, "test_id": tc.test_id, "business_summary": tc.business_summary or tc.scenario,
            "kind": tc.kind, "expected_requirement": tc.expected_requirement,
            "expected_case_created": tc.expected_case_created, "status": tc.status,
            "review_comment": tc.review_comment, "priority": tc.priority,
            "source": "AI" if (tc.created_by or "").startswith("agent:") else "Scenario"}
    if business:
        return base
    return {**base, "scenario": tc.scenario, "preconditions": tc.preconditions,
            "input_conditions": tc.input_conditions, "validation_criteria": tc.validation_criteria,
            "rule_coverage": tc.rule_coverage, "rule_set_id": tc.rule_set_id}


def _result_out(r: UatResult, business: bool, test_case: Optional[UatTestCase] = None,
                comparison: Optional[UatComparison] = None) -> dict[str, Any]:
    review = r.review or {}
    reason = r.error or "; ".join((r.check or {}).get("reasons") or review.get("reasons") or [])
    base = {"id": r.id, "test_id": r.test_id, "verdict": r.verdict,
            "business_summary": (test_case.business_summary if test_case else None),
            "business_explanation": review.get("business_explanation"),
            "reason": reason,
            "comparison": ({"endpoint": comparison.endpoint_name, "identical": comparison.identical,
                            "differences": (comparison.summary or {}).get("totalDifferences"),
                            "error": comparison.error} if comparison else None)}
    if business:
        return base
    return {**base, "test_case_id": r.test_case_id, "verdict_source": r.verdict_source,
            "payload": r.payload, "changes": r.changes, "response_status": r.response_status,
            "response_body": r.response_body, "latency_ms": r.latency_ms, "check": r.check,
            "review": review, "analysis": r.analysis, "error": r.error}


def _run_out(session: Session, run: UatRun, business: bool) -> dict[str, Any]:
    results = list(session.execute(select(UatResult).where(UatResult.run_id == run.id)
                                   .order_by(UatResult.test_id)).scalars())
    cases = {tc.id: tc for tc in session.execute(
        select(UatTestCase).where(UatTestCase.case_id == run.case_id)).scalars()}
    comparisons = {c.result_id: c for c in session.execute(
        select(UatComparison).where(UatComparison.result_id.in_([r.id for r in results]))).scalars()}
    return {
        "id": run.id, "cycle": run.cycle, "status": run.status, "executor": run.executor,
        "passed": run.passed, "failed": run.failed, "errors": run.errors,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "results": [_result_out(r, business, cases.get(r.test_case_id), comparisons.get(r.id)) for r in results],
    }


def _rule_rows(session: Session, rule_set_id: str) -> list[dict[str, Any]]:
    rules = session.execute(select(Rule).where(Rule.rule_set_id == rule_set_id)
                            .order_by(Rule.row_no)).scalars()
    return [{"id": r.id, "country": r.ctry_cd, "requirement_group": r.sirg_cd,
             "shipment_type": r.shipment_type, "currency": r.currency, "min_value": r.min_value,
             "max_value": r.max_value, "other_logic": r.other_logic} for r in rules]


def _next_code(session: Session, country: str) -> str:
    year = _today().year
    prefix = f"ONB-{year}-{country}-"
    count = session.execute(
        select(func.count()).select_from(OnboardingCase).where(OnboardingCase.code.like(f"{prefix}%"))
    ).scalar_one()
    return f"{prefix}{count + 1:03d}"


def ensure_builtin_template(session: Session) -> None:
    """The demo sample payload (matching the mock CCRE) is always available."""
    exists = session.execute(select(func.count()).select_from(PayloadTemplate)
                             .where(PayloadTemplate.created_by == "system")).scalar_one()
    if not exists:
        session.add(PayloadTemplate(
            name="Built-in sample shipment (demo)", country=None, body=builtin_sample_payload(),
            notes="Matches the mock CCRE endpoint. Replace with your real sample payload.",
            created_by="system"))
        session.commit()


# --------------------------------------------------------------------------- #
# lifecycle metadata
# --------------------------------------------------------------------------- #

@router.get("/lifecycle", tags=["lifecycle"])
def lifecycle_meta(_: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    return {
        "stages": [{"key": s.key, "label": s.label, "business_label": s.business_label,
                    "states": [str(x) for x in s.states]} for s in STAGES],
        "states": {str(k): v for k, v in STATE_LABELS.items()},
        "transitions": [{"name": t.name, "label": t.label, "source": str(t.source),
                         "target": str(t.target), "actors": t.actor_names} for t in TRANSITIONS],
        "milestones": list(MILESTONES),
        "questions": list(QUESTIONS),
    }


# --------------------------------------------------------------------------- #
# onboardings
# --------------------------------------------------------------------------- #

def _waiting(session: Session, case: OnboardingCase, user: CurrentUser) -> Optional[dict[str, Any]]:
    from .collab import waiting_info

    return waiting_info(session, case, user)


def _summary(session: Session, case: OnboardingCase) -> dict[str, Any]:
    state = State(case.state)
    stage = stage_of(state)
    tl = current_timeline(session, case.id)
    planned_rtp = None
    if tl is not None and tl.status == "APPROVED" and tl.milestones:
        planned_rtp = tl.milestones[-1].planned_end.isoformat()
    return {"id": case.id, "code": case.code, "country": case.ctry_cd, "title": case.title,
            "state": str(state), "state_label": STATE_LABELS[state],
            "stage": stage.key if stage else None, "planned_rtp": planned_rtp,
            "created_at": case.created_at.isoformat() if case.created_at else None}


@router.get("/onboardings", tags=["lifecycle"])
def list_onboardings(user: CurrentUser = Depends(current_user),
                     session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    cases = session.execute(select(OnboardingCase).order_by(OnboardingCase.created_at.desc())).scalars()
    return [_summary(session, c) for c in cases if user.can_see(c.ctry_cd)]


@router.post("/onboardings", status_code=201, tags=["lifecycle"])
def create_onboarding(body: S.OnboardingCreate, user: CurrentUser = Depends(current_user),
                      session: Session = Depends(get_session)) -> dict[str, Any]:
    country = body.ctry_cd.upper()
    if not user.can_see(country):
        raise HTTPException(403, f"You are not assigned to country {country}.")
    if user.role == UserRole.PM:
        raise HTTPException(403, "Onboardings are raised by the business team or the CCRE team.")
    code = (body.code or _next_code(session, country)).strip()
    if session.execute(select(OnboardingCase).where(OnboardingCase.code == code)).scalar_one_or_none():
        raise HTTPException(409, f"An onboarding with code {code} already exists.")
    case = OnboardingCase(code=code, ctry_cd=country, title=body.title.strip(), gccp_ref=body.gccp_ref,
                          priority=body.priority, state=str(State.INTAKE))
    session.add(case)
    session.flush()
    _audit(session, case.id, user.label, "case:created", {"code": code, "country": country})
    session.commit()
    return _summary(session, case)


@router.get("/onboardings/{case_id}", tags=["lifecycle"])
def onboarding_overview(case_id: str, user: CurrentUser = Depends(current_user),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    state = State(case.state)
    business = user.is_business
    ctx = gate_context(session, case)

    role = Role(str(user.role))
    actions = []
    for t in transitions_from(state):
        if business and Role.BUSINESS not in t.actors:
            continue
        blocked = can_fire(t, role, ctx)
        if t.kind == "system":
            continue
        actions.append({"name": t.name, "label": t.label, "target": str(t.target), "kind": t.kind,
                        "actors": t.actor_names, "allowed": not blocked, "blocked_by": blocked,
                        "mine": role in t.actors})

    tl = current_timeline(session, case.id)
    if business and (tl is None or tl.status != "APPROVED"):
        tl = None
    counts = dict(session.execute(
        select(UatTestCase.status, func.count()).where(UatTestCase.case_id == case.id)
        .group_by(UatTestCase.status)).all())
    run = latest_run(session, case.id)
    show_run = run is not None and (not business or state in _BUSINESS_SEES_RESULTS)
    out = {
        **_summary(session, case),
        "cycle": correction_cycle(session, case.id),
        "requirement": _requirement_out(latest_requirement(session, case.id)),
        "timeline": _timeline_out(tl),
        "test_case_counts": counts if (not business or state in _BUSINESS_SEES_TESTS) else {},
        "latest_run": ({"id": run.id, "cycle": run.cycle, "passed": run.passed, "failed": run.failed,
                        "errors": run.errors} if show_run else None),
        "actions": actions,
        "waiting": _waiting(session, case, user),
        "gates": {"validation_clean": ctx.validation_clean, "package_complete": ctx.package_complete,
                  "tests_total": ctx.tests_total, "tests_passed": ctx.tests_passed,
                  "execution_complete": ctx.execution_complete} if not business else None,
    }
    if not business:
        rs = case_rule_set(session, case)
        out["m2c"] = ({"rule_set_id": rs.id, "version": rs.version, "label": rs.label,
                       "rules": session.execute(select(func.count()).select_from(Rule)
                                                .where(Rule.rule_set_id == rs.id)).scalar_one()}
                      if rs else None)
        if ctx.report is not None:
            out["validation"] = {"clean": ctx.report.is_clean, "blockers": len(ctx.report.blockers),
                                 "cautions": len(ctx.report.cautions)}
        from tools.workflow.case_facts import latest_dmg_task

        dmg = latest_dmg_task(session, case.id)
        out["dmg"] = {"status": dmg.status if dmg else None, "completed": ctx.dmg_complete}
    return out


# --------------------------------------------------------------------------- #
# transitions (with their side effects)
# --------------------------------------------------------------------------- #

def _record_milestone_actuals(session: Session, case: OnboardingCase, new_state: State) -> None:
    tl = current_timeline(session, case.id)
    if tl is None or tl.status != "APPROVED":
        return
    by_stage = {m.stage: m for m in tl.milestones}
    today = _today()
    if new_state == State.COMPLETED:
        rtp = by_stage.get("RTP")
        if rtp and rtp.actual_end is None:
            rtp.actual_end = today
        return
    target = _STATE_MILESTONE.get(new_state)
    if target is None:
        return
    current = by_stage.get(target)
    if current and current.actual_start is None:
        current.actual_start = today
    for stage in _MILESTONE_ORDER[: _MILESTONE_ORDER.index(target)]:
        earlier = by_stage.get(stage)
        if earlier and earlier.actual_end is None:
            earlier.actual_start = earlier.actual_start or today
            earlier.actual_end = today


def _after_transition(session: Session, case: OnboardingCase, name: str, user: CurrentUser) -> None:
    if name == "approve_timeline":
        tl = current_timeline(session, case.id)
        if tl is not None:
            tl.status = "APPROVED"
            tl.approved_by = user.label
            tl.approved_at = dt.datetime.now(dt.timezone.utc)
            if tl.milestones:
                case.approved_rtp = tl.milestones[-1].planned_end
            _audit(session, case.id, user.label, "timeline:published",
                   {"version": tl.version, "rtp": case.approved_rtp.isoformat() if case.approved_rtp else None})
    elif name == "confirm_production":
        case.actual_rtp = _today()
    _record_milestone_actuals(session, case, State(case.state))


def apply_transition(session: Session, case: OnboardingCase, name: str, actor: str, role: Role,
                     user: Optional[CurrentUser], comment: Optional[str] = None) -> None:
    transition = find_transition(State(case.state), name)
    ctx = gate_context(session, case)
    if transition is not None and transition.requires_clean_validation and ctx.has_rule_set:
        rs = case_rule_set(session, case)
        ctx.report, _ = validate_rule_set(session, rs.id, case_id=case.id, persist=True)
    rs = case_rule_set(session, case)
    fire(session, case, name, actor=actor, actor_role=role, ctx=ctx, comment=comment,
         rule_set_version=rs.version if rs else None)
    if user is not None:
        _after_transition(session, case, name, user)
    else:
        _record_milestone_actuals(session, case, State(case.state))
    if State(case.state) == State.SANITY_CHECK:
        # Entering the sanity check runs it straight away — nobody has to start it by hand.
        from tools import sanity
        sanity.run(session, case, "system:on-entry")


@router.post("/onboardings/{case_id}/transition", tags=["lifecycle"])
def transition(case_id: str, body: S.LifecycleTransition, user: CurrentUser = Depends(current_user),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    try:
        apply_transition(session, case, body.name, actor=user.label, role=Role(str(user.role)),
                         user=user, comment=body.comment)
    except TransitionError as exc:
        session.rollback()
        raise HTTPException(409, detail={"message": exc.message, "reasons": exc.reasons}) from exc
    session.commit()
    return _summary(session, case)


# --------------------------------------------------------------------------- #
# 1. intake — chat or form
# --------------------------------------------------------------------------- #

def _save_requirement(session: Session, case: OnboardingCase, mode: str, text: str,
                      structured: dict[str, Any], user: CurrentUser) -> Requirement:
    previous = latest_requirement(session, case.id)
    req = Requirement(case_id=case.id, version=(previous.version + 1) if previous else 1, mode=mode,
                      text=text, structured=structured, created_by=user.label)
    session.add(req)
    case.requirement_text = text
    if structured.get("requested_rtp"):
        try:
            case.requested_rtp = dt.date.fromisoformat(str(structured["requested_rtp"]))
        except ValueError:
            pass
    if structured.get("business_owner"):
        case.business_owner = str(structured["business_owner"])[:128]
    _audit(session, case.id, user.label, "intake:requirement_captured",
           {"mode": mode, "version": req.version})
    return req


@router.get("/onboardings/{case_id}/intake", tags=["intake"])
def intake_view(case_id: str, user: CurrentUser = Depends(current_user),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    from tools.core.models import IntakeMessage

    case = _case(session, case_id, user)
    messages = session.execute(select(IntakeMessage).where(IntakeMessage.case_id == case.id)
                               .order_by(IntakeMessage.id)).scalars()
    return {"messages": [{"role": m.role, "author": m.author, "text": m.text,
                          "at": m.at.isoformat() if m.at else None} for m in messages],
            "requirement": _requirement_out(latest_requirement(session, case.id))}


# -- M2C criteria: what every requirement must state ------------------------- #

def _m2c_merge(session: Session, case: OnboardingCase, text: str, given: dict[str, Any]) -> dict[str, Any]:
    """Criteria read from the text, overlaid by what the user filled in (the form wins)."""
    options = F.load_options(session, case.ctry_cd)
    merged = F.extract(text, options) if text and text.strip() else {}
    for key, value in (given or {}).items():
        if value not in (None, "", []):
            merged[key] = value
    return F.check(merged, options)


def _m2c_structured(case: OnboardingCase, checked: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    c = checked["criteria"]
    out = dict(base)
    out["m2c"] = c
    out["m2c_check"] = {k: checked[k] for k in ("errors", "warnings", "missing", "complete")}
    out["m2c_row"] = checked["m2c_row"]
    out["m2c_view"] = [{"key": f["key"], "label": label, "value": value}
                       for f, (label, value) in zip(F.FIELDS, F.describe(c))]
    out["country_code"] = case.ctry_cd
    if isinstance(c.get("requirement_groups"), list):
        out["requirement_groups"] = sorted(set(c["requirement_groups"]) | set(out.get("requirement_groups") or []))
    if c.get("shipment_type") not in (None, F.NA):
        out["shipment_type"] = c["shipment_type"]
    if c.get("currency") not in (None, F.NA):
        out["currency"] = c["currency"]
    return out


def _criteria_sentence(case: OnboardingCase, c: dict[str, Any]) -> str:
    # Labels without their format hints ("(DD-MM-YYYY)"), so readers do not take them for codes.
    parts = [f"{label.split(' (')[0]}: {value}" for label, value in F.describe(c)]
    return f"{case.ctry_cd} requirement. " + "; ".join(parts)


@router.get("/onboardings/{case_id}/intake/fields", tags=["intake"])
def intake_fields(case_id: str, user: CurrentUser = Depends(current_user),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    """The M2C criteria to gather, with dropdown values and what each field accepts."""
    case = _case(session, case_id, user)
    options = F.load_options(session, case.ctry_cd)
    req = latest_requirement(session, case.id)
    current = (req.structured or {}).get("m2c") if req else None
    current = dict(current or {"country": case.ctry_cd, "region": options.get("region_default")})
    if "conditions" not in current:
        current["conditions"] = F.to_conditions(current, req.text if req else "")
    return {"fields": F.field_specs(options), "options": options, "current": current,
            "conditions": {"fields": F.CONDITION_FIELDS, "options": F.condition_options(session)}}


@router.post("/onboardings/{case_id}/intake/extract", tags=["intake"])
def intake_extract(case_id: str, body: S.IntakeExtract, user: CurrentUser = Depends(require(*_INTAKE_ROLES)),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    """NLP: read the M2C criteria from the text; say what is still missing. Saves nothing."""
    case = _case(session, case_id, user)
    out = _m2c_merge(session, case, body.text, body.m2c)
    # The same reading as condition-builder rows, for the form.
    out["conditions"] = body.m2c.get("conditions") if isinstance(body.m2c.get("conditions"), list)         else F.to_conditions(out["criteria"], body.text)
    return out


@router.post("/onboardings/{case_id}/intake/chat", tags=["intake"])
def intake_chat(case_id: str, body: S.IntakeChat, user: CurrentUser = Depends(require(*_INTAKE_ROLES)),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    """The intake conversation. The code decides what is still missing and asks for it,
    one M2C column at a time; the model only writes the final interpretation."""
    from tools.core.models import IntakeMessage

    case = _case(session, case_id, user)
    _require_state(case, State.INTAKE)
    session.add(IntakeMessage(case_id=case.id, role="user", author=user.label, text=body.message.strip()))
    session.flush()
    messages = list(session.execute(select(IntakeMessage).where(IntakeMessage.case_id == case.id)
                                    .order_by(IntakeMessage.id)).scalars())
    options = F.load_options(session, case.ctry_cd)
    previous = latest_requirement(session, case.id)
    criteria: dict[str, Any] = dict((previous.structured or {}).get("m2c") or {}) if previous else {}
    asked: Optional[str] = None
    for m in messages:
        if m.role == "assistant":
            asked = next((f["key"] for f in F.FIELDS if f["question"][:40] in m.text), None)
            continue
        for key, value in F.extract(m.text, options).items():
            criteria[key] = value
        if asked:
            answer = F.answer_for(asked, m.text, options)
            if answer is not None:
                criteria[asked] = answer
        asked = None
    checked = F.check(criteria, options)

    requirement = None
    complete = checked["complete"]
    if checked["errors"]:
        key, problem = next(iter(checked["errors"].items()))
        spec = F.FIELD_BY_KEY[key]
        reply = f"{spec['label']}: {problem}\n{spec['question']}\nAccepted: {spec['accepted']}"
    elif checked["missing"]:
        nxt = checked["missing"][0]
        got = [f"{label}: {value}" for label, value in F.describe(checked["criteria"])
               if not value.startswith("— ")]
        left = len(checked["missing"])
        intro = "" if len(got) > 1 else "Thanks. I need the details the CCRE team writes into the M2C, one at a time.\n\n"
        so_far = ("\n\nSo far: " + "; ".join(got) + ".") if len(got) > 1 else ""
        reply = (f"{intro}{nxt['question']}\nAccepted: {nxt['accepted']}\n"
                 f"({left} question{'s' if left != 1 else ''} left){so_far}")
    else:
        user_text = "\n".join(m.text for m in messages if m.role == "user")
        form = {"country_code": case.ctry_cd, "requirement_groups": checked["criteria"]["requirement_groups"],
                "shipment_type": checked["criteria"].get("shipment_type")}
        reading = _advise(advisory.interpret_form, case, form, user_text)
        req = _save_requirement(session, case, "CHAT", user_text, _m2c_structured(case, checked, reading), user)
        requirement = _requirement_out(req)
        lines = "\n".join(f"- {label}: {value}" for label, value in F.describe(checked["criteria"]))
        notes = "".join(f"\n! {F.FIELD_BY_KEY[k]['label']}: {w}" for k, w in checked["warnings"].items())
        reply = (f"Here is the requirement for the M2C:\n{lines}{notes}\n\n"
                 "If anything is wrong, just tell me (e.g. 'effective date 01-12-2026'). "
                 "Otherwise click 'Submit requirement for approval'.")
    session.add(IntakeMessage(case_id=case.id, role="assistant", author="agent:intake_assistant", text=reply))
    session.commit()
    return {"reply": reply, "complete": complete, "requirement": requirement,
            "missing": checked["missing"], "criteria": checked["criteria"]}


@router.post("/onboardings/{case_id}/intake/form", tags=["intake"])
def intake_form(case_id: str, body: S.IntakeForm, user: CurrentUser = Depends(require(*_INTAKE_ROLES)),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.INTAKE)
    given = dict(body.m2c or {})
    groups = [g.strip().upper() for g in body.requirement_groups if g.strip()]
    if groups and not given.get("requirement_groups"):
        given["requirement_groups"] = groups
    for key in ("shipment_type", "currency"):
        if getattr(body, key) and not given.get(key):
            given[key] = getattr(body, key)
    checked = _m2c_merge(session, case, body.description, given)
    description = body.description.strip() or _criteria_sentence(case, checked["criteria"])
    form = body.model_dump(mode="json", exclude={"description", "m2c"})
    form["country_code"] = case.ctry_cd
    form["requirement_groups"] = checked["criteria"].get("requirement_groups") or groups
    if checked["criteria"].get("shipment_type") not in (None, F.NA):
        form["shipment_type"] = checked["criteria"]["shipment_type"]
    structured = _advise(advisory.interpret_form, case, form, description)
    req = _save_requirement(session, case, "FORM", description, _m2c_structured(case, checked, structured), user)
    session.commit()
    return {"requirement": _requirement_out(req), "check": {k: checked[k] for k in
                                                             ("errors", "warnings", "missing", "complete")}}


# --------------------------------------------------------------------------- #
# 2. timeline
# --------------------------------------------------------------------------- #

@router.get("/timeline/questions", tags=["timeline"])
def timeline_questions(_: CurrentUser = Depends(require_internal)) -> dict[str, Any]:
    return {"questions": list(QUESTIONS), "milestones": list(MILESTONES)}


def _store_plan(session: Session, case: OnboardingCase, plan: dict[str, Any], answers: dict[str, Any],
                facts: dict[str, Any], user: CurrentUser) -> Timeline:
    previous = current_timeline(session, case.id)
    if previous is not None:
        previous.status = "SUPERSEDED"
    names = {m["stage"]: m for m in MILESTONES}
    tl = Timeline(case_id=case.id, version=(previous.version + 1) if previous else 1, status="DRAFT",
                  answers=answers, facts=facts, assumptions=plan.get("assumptions", []),
                  risks=list(dict.fromkeys(plan.get("risks", []) + plan["risk"]["risks"])),
                  open_questions=plan.get("open_questions", []), at_risk=plan["risk"]["at_risk"],
                  created_by=user.label)
    session.add(tl)
    session.flush()
    for seq, m in enumerate(plan["milestones"], start=1):
        meta = names[m["stage"]]
        session.add(Milestone(timeline_id=tl.id, seq=seq, stage=m["stage"], name=meta["name"],
                              owner=meta["owner"], planned_start=dt.date.fromisoformat(str(m["start"])),
                              planned_end=dt.date.fromisoformat(str(m["end"])), notes=m.get("notes")))
    session.flush()
    session.refresh(tl)
    return tl


@router.post("/onboardings/{case_id}/timeline/generate", tags=["timeline"])
def generate_timeline(case_id: str, body: S.TimelineAnswers,
                      user: CurrentUser = Depends(require(*_TIMELINE_ROLES)),
                      session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.TIMELINE_PLANNING)
    try:
        answers = normalise_answers(body.answers)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    req = latest_requirement(session, case.id)
    structured = req.structured if req else {}
    rs = case_rule_set(session, case)
    facts = complexity_facts(session, case.ctry_cd, structured, rs.id if rs else None)
    baseline = estimate(facts, answers)
    plan = _advise(advisory.plan_timeline, case, structured, facts, answers, baseline)
    tl = _store_plan(session, case, plan, answers, facts, user)
    _audit(session, case.id, user.label, "timeline:generated",
           {"version": tl.version, "at_risk": tl.at_risk, "agent": "timeline_planner"})
    session.commit()
    return _timeline_out(tl)


@router.patch("/onboardings/{case_id}/timeline", tags=["timeline"])
def edit_timeline(case_id: str, body: S.MilestoneEdits,
                  user: CurrentUser = Depends(require(*_TIMELINE_ROLES)),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.TIMELINE_PLANNING, State.TIMELINE_REVIEW)
    tl = current_timeline(session, case.id)
    if tl is None:
        raise HTTPException(409, "Generate a timeline first.")
    edits = [m.model_dump(mode="json") for m in body.milestones]
    try:
        risk = validate_plan(edits, tl.answers)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    by_stage = {m.stage: m for m in tl.milestones}
    for e in edits:
        m = by_stage[e["stage"]]
        m.planned_start = dt.date.fromisoformat(e["start"])
        m.planned_end = dt.date.fromisoformat(e["end"])
        if e.get("notes") is not None:
            m.notes = e["notes"]
    tl.at_risk = risk["at_risk"]
    tl.risks = [r for r in (tl.risks or []) if "Planned RTP" not in r] + risk["risks"]
    _audit(session, case.id, user.label, "timeline:edited", {"version": tl.version})
    session.commit()
    session.refresh(tl)
    return _timeline_out(tl)


@router.get("/onboardings/{case_id}/timeline", tags=["timeline"])
def get_timeline(case_id: str, user: CurrentUser = Depends(current_user),
                 session: Session = Depends(get_session)) -> Optional[dict[str, Any]]:
    case = _case(session, case_id, user)
    tl = current_timeline(session, case.id)
    if user.is_business and (tl is None or tl.status != "APPROVED"):
        return None
    return _timeline_out(tl)


# --------------------------------------------------------------------------- #
# 3. rule config + DMG (M2C draft) and sanity check
# --------------------------------------------------------------------------- #

@router.post("/onboardings/{case_id}/m2c/start", tags=["m2c"])
def m2c_start(case_id: str, user: CurrentUser = Depends(require_ccre),
              session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.RULE_CONFIG)
    rs, copied = start_m2c_draft(session, case, user.label)
    session.commit()
    return {"rule_set_id": rs.id, "version": rs.version, "label": rs.label, "rules_copied": copied}


@router.get("/onboardings/{case_id}/m2c", tags=["m2c"])
def m2c_view(case_id: str, user: CurrentUser = Depends(require_internal),
             session: Session = Depends(get_session)) -> dict[str, Any]:
    from .routes import _rule_out

    case = _case(session, case_id, user)
    rs = case_rule_set(session, case)
    if rs is None:
        return {"rule_set": None, "rules": [], "proposals": []}
    rules = session.execute(select(Rule).where(Rule.rule_set_id == rs.id)
                            .options(selectinload(Rule.bindings)).order_by(Rule.row_no)).scalars()
    proposals = session.execute(select(ProposedChange).where(ProposedChange.case_id == case.id)
                                .order_by(ProposedChange.created_at.desc())).scalars()
    return {
        "rule_set": {"id": rs.id, "version": rs.version, "label": rs.label, "sealed": rs.sealed},
        "rules": [_rule_out(r).model_dump(mode="json") for r in rules],
        "proposals": [{"id": p.id, "origin": p.origin, "status": p.status, "rationale": p.rationale,
                       "payload": p.payload,
                       "created_at": p.created_at.isoformat() if p.created_at else None} for p in proposals],
        "note": "The M2C draft covers the Import tab. The other M2C tabs that power it are configured later.",
    }


@router.post("/onboardings/{case_id}/m2c/draft", tags=["m2c"])
def m2c_draft(case_id: str, body: S.M2CDraftRequest, user: CurrentUser = Depends(require_ccre),
              session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.RULE_CONFIG)
    if case_rule_set(session, case) is None:
        raise HTTPException(409, "Start the M2C draft first.")
    req = latest_requirement(session, case.id)
    if req is None:
        raise HTTPException(409, "There is no approved requirement to convert.")
    text = (req.text or "") + (f"\n\nCCRE notes: {body.notes}" if body.notes else "")
    return _advise(advisory.draft_rules, session, case, text, req.structured, user.label)


@router.post("/onboardings/{case_id}/m2c/validate", tags=["m2c"])
def m2c_validate(case_id: str, user: CurrentUser = Depends(require_internal),
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    rs = case_rule_set(session, case)
    if rs is None:
        raise HTTPException(409, "Start the M2C draft first.")
    report, run_id = validate_rule_set(session, rs.id, case_id=case.id, persist=True)
    session.commit()
    return {**report.as_dict(), "run_id": run_id, "rule_set_id": rs.id}


# --------------------------------------------------------------------------- #
# 4. UAT test cases
# --------------------------------------------------------------------------- #

@router.post("/onboardings/{case_id}/uat/test-cases/generate", tags=["uat"])
def generate_test_cases(case_id: str, body: S.GenerateTestCases, user: CurrentUser = Depends(require_ccre),
                        session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    case = _case(session, case_id, user)
    # Preparation may start while the M2C is still being finalised.
    _require_state(case, State.RULE_CONFIG, State.SANITY_CHECK, State.UAT_TC_PREP)
    rs = case_rule_set(session, case)
    if rs is None:
        raise HTTPException(409, "Start the M2C draft first — test cases are written from it.")
    rows = [r for r in _rule_rows(session, rs.id) if r["country"] == case.ctry_cd]
    if not rows:
        raise HTTPException(400, "The M2C draft has no rules for this country yet.")
    suite = _advise(advisory.design_tests, rs.version, rows, body.notes)
    # Regenerating replaces only AI rows nobody has approved; decided rows and
    # scenarios people added stay.
    for old in session.execute(select(UatTestCase).where(
            UatTestCase.case_id == case.id, UatTestCase.status.in_(["DRAFT", "REJECTED"]),
            UatTestCase.created_by.like("agent:%"))).scalars():
        session.delete(old)
    taken = set(session.execute(select(UatTestCase.test_id).where(UatTestCase.case_id == case.id)).scalars())
    created = []
    for c in suite["cases"]:
        if c["test_id"] in taken:
            continue
        tc = UatTestCase(case_id=case.id, rule_set_id=rs.id, test_id=c["test_id"], scenario=c["scenario"],
                         kind=c["kind"], business_summary=c.get("business_summary"),
                         preconditions=c.get("preconditions", []), input_conditions=c.get("input_conditions", []),
                         expected_requirement=c.get("expected_requirement"),
                         expected_case_created=bool(c.get("expected_case_created", True)),
                         validation_criteria=c.get("validation_criteria"),
                         rule_coverage=c.get("rule_coverage", []), priority=c.get("priority", "medium"),
                         status="DRAFT", created_by="agent:test_case_designer")
        session.add(tc)
        created.append(tc)
    _audit(session, case.id, user.label, "uat:test_cases_generated",
           {"count": len(created), "uncovered": suite.get("uncovered_conditions", [])})
    session.commit()
    return [_test_case_out(tc, business=False) for tc in created]


@router.get("/onboardings/{case_id}/uat/test-cases", tags=["uat"])
def list_test_cases(case_id: str, user: CurrentUser = Depends(current_user),
                    session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    case = _case(session, case_id, user)
    if user.is_business and State(case.state) not in _BUSINESS_SEES_TESTS:
        return []
    cases = session.execute(select(UatTestCase).where(UatTestCase.case_id == case.id)
                            .order_by(UatTestCase.test_id)).scalars()
    return [_test_case_out(tc, business=user.is_business) for tc in cases]


# --------------------------------------------------------------------------- #
# 5. UAT execution — sample payloads and runs
# --------------------------------------------------------------------------- #

@router.get("/uat/templates", tags=["uat"])
def list_templates(_: CurrentUser = Depends(require_internal),
                   session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    ensure_builtin_template(session)
    return [{"id": t.id, "name": t.name, "country": t.country, "body": t.body, "notes": t.notes,
             "created_by": t.created_by} for t in session.execute(
                 select(PayloadTemplate).order_by(PayloadTemplate.created_at)).scalars()]


@router.post("/uat/templates", status_code=201, tags=["uat"])
def add_template(body: S.TemplateCreate, user: CurrentUser = Depends(require_ccre),
                 session: Session = Depends(get_session)) -> dict[str, Any]:
    payload = body.body
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"The sample payload is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(400, "The sample payload must be a non-empty JSON object.")
    t = PayloadTemplate(name=body.name.strip(), country=(body.country or "").upper() or None, body=payload,
                        notes=body.notes, created_by=user.label)
    session.add(t)
    _audit(session, None, user.label, "uat:template_added", {"name": t.name, "country": t.country})
    session.commit()
    return {"id": t.id, "name": t.name, "country": t.country, "body": t.body, "notes": t.notes}


@router.delete("/uat/templates/{template_id}", tags=["uat"])
def delete_template(template_id: str, user: CurrentUser = Depends(require_ccre),
                    session: Session = Depends(get_session)) -> dict[str, str]:
    t = session.get(PayloadTemplate, template_id)
    if t is None:
        raise HTTPException(404, "No such template.")
    session.delete(t)
    session.commit()
    return {"status": "deleted"}


@router.post("/onboardings/{case_id}/uat/runs", tags=["uat"])
def start_run(case_id: str, body: S.RunRequest, user: CurrentUser = Depends(require_ccre),
              session: Session = Depends(get_session)) -> dict[str, Any]:
    from .uat import execute_run

    case = _case(session, case_id, user)
    _require_state(case, State.UAT_EXECUTION)
    ensure_builtin_template(session)
    template = (session.get(PayloadTemplate, body.template_id) if body.template_id else
                session.execute(select(PayloadTemplate).where(
                    (PayloadTemplate.country == case.ctry_cd) | PayloadTemplate.country.is_(None))
                    .order_by(PayloadTemplate.country.is_(None), PayloadTemplate.created_at.desc())
                    .limit(1)).scalar_one_or_none())
    if template is None:
        raise HTTPException(400, "No sample payload is available — add one first.")
    endpoint = compare_endpoint = None
    if body.endpoint_id:
        endpoint = session.get(ExecutionEndpoint, body.endpoint_id)
        if endpoint is None or not endpoint.active:
            raise HTTPException(400, "That endpoint is not available; ask an admin.")
    if body.compare_endpoint_id:
        if endpoint is None:
            raise HTTPException(400, "Choose the main endpoint before a comparison endpoint.")
        compare_endpoint = session.get(ExecutionEndpoint, body.compare_endpoint_id)
        if compare_endpoint is None or not compare_endpoint.active or compare_endpoint.id == endpoint.id:
            raise HTTPException(400, "Choose a different, active endpoint to compare against.")
    run = _advise(execute_run, session, advisory, case, template, user.label, endpoint, compare_endpoint)

    # Execution complete → hand over to the CCRE team's review automatically.
    if gate_context(session, case).execution_complete:
        apply_transition(session, case, "complete_execution", actor="system", role=Role.SYSTEM, user=None,
                         comment=f"UAT run {run.id} finished: {run.passed} passed, "
                                 f"{run.failed} failed, {run.errors} errors")
    session.commit()
    return {"run": _run_out(session, run, business=False), "state": case.state,
            "state_label": STATE_LABELS[State(case.state)]}


@router.get("/onboardings/{case_id}/uat/runs", tags=["uat"])
def list_runs(case_id: str, user: CurrentUser = Depends(current_user),
              session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    case = _case(session, case_id, user)
    if user.is_business:
        if State(case.state) not in _BUSINESS_SEES_RESULTS:
            return []
        run = latest_run(session, case.id)
        return [_run_out(session, run, business=True)] if run else []
    runs = session.execute(select(UatRun).where(UatRun.case_id == case.id)
                           .order_by(UatRun.started_at.desc())).scalars()
    return [_run_out(session, r, business=False) for r in runs]


@router.post("/uat/results/{result_id}/analyse", tags=["uat"])
def analyse_result(result_id: str, user: CurrentUser = Depends(require_ccre),
                   session: Session = Depends(get_session)) -> dict[str, Any]:
    result = session.get(UatResult, result_id)
    if result is None:
        raise HTTPException(404, "No such result.")
    run = session.get(UatRun, result.run_id)
    case = _case(session, run.case_id, user)
    tc = session.get(UatTestCase, result.test_case_id)
    evidence = {
        "test_id": result.test_id, "verdict": result.verdict, "error": result.error,
        "test_case": _test_case_out(tc, business=False) if tc else None,
        "payload_changes": result.changes, "response_status": result.response_status,
        "response_body": result.response_body, "check": result.check, "review": result.review,
    }
    analysis = _advise(advisory.analyse_failure, evidence)
    result.analysis = analysis
    _audit(session, case.id, "agent:failure_analyst", "advisory:failure_analysis",
           {"requested_by": user.label, "test_id": result.test_id, "analysis": analysis})
    session.commit()
    return {"result_id": result.id, "analysis": analysis}


# Re-exported for tests and the app.
__all__ = ["router", "ensure_builtin_template", "apply_transition", "executable_test_cases"]
