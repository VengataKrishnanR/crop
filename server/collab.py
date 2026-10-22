"""Collaboration routes: approval reminders, the DMG email task, the sanity
checklist, and row-by-row UAT test case decisions (including "+ scenario").
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.core.db import get_session
from tools.core.mailer import clean_addresses, get_settings, send_email
from tools.core.models import AuditEvent, DmgTask, Notification, OnboardingCase, Rule, UatTestCase, User
from tools.core.security import CCRE_ROLES, UserRole
from tools.dmg import PLACEHOLDERS, fill, get_template, unknown_placeholders, values_for
from tools.timeline import complexity_facts
from tools.workflow import STATE_LABELS, State, waiting_roles
from tools.workflow.case_facts import case_rule_set, gate_context, latest_dmg_task, latest_requirement

from .auth import CurrentUser, current_user, ensure_country, require, require_ccre, require_internal
from .lifecycle import _advise, _audit, _case, _require_state, _rule_rows, _test_case_out, advisory

router = APIRouter()

REMINDER_COOLDOWN = dt.timedelta(minutes=10)
ROLE_NAMES = {"PM": "PM", "CCRE_CONSULTANT": "CCRE consultant", "CCRE_TEAM": "CCRE team",
              "BUSINESS": "business team", "ADMIN": "admin"}


def _naive(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


# --------------------------------------------------------------------------- #
# 1. waiting-for-approval banner and reminder email
# --------------------------------------------------------------------------- #

def waiting_info(session: Session, case: OnboardingCase, user: CurrentUser) -> Optional[dict[str, Any]]:
    """Who the onboarding is waiting for, and whether this user can act."""
    state = State(case.state)
    roles = waiting_roles(state)
    if not roles:
        return None
    last = session.execute(
        select(Notification.at).where(Notification.case_id == case.id, Notification.kind == "REMINDER",
                                      Notification.state == case.state)
        .order_by(Notification.at.desc()).limit(1)).scalar_one_or_none()
    who = " or ".join(ROLE_NAMES.get(r, r) for r in roles)
    return {
        "roles": roles,
        "can_act": str(user.role) in roles,
        "message": f"Waiting for the {who} — {STATE_LABELS[state]}.",
        "last_reminder_at": last.isoformat() if last else None,
    }


def _recipients(session: Session, case: OnboardingCase, roles: list[str]) -> tuple[list[str], list[str]]:
    users = list(session.execute(select(User).where(User.active.is_(True))).scalars())

    def involved(u: User) -> bool:
        return u.role != UserRole.BUSINESS or case.ctry_cd in set(u.countries or [])

    to = sorted({u.email for u in users if u.role in roles and involved(u)})
    cc = sorted({u.email for u in users if involved(u)} - set(to))
    return to, cc


class ReminderIn(BaseModel):
    message: Optional[str] = Field(default=None, max_length=2000)


@router.post("/onboardings/{case_id}/remind", tags=["notifications"])
def send_reminder(case_id: str, body: ReminderIn, user: CurrentUser = Depends(current_user),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    """Email the approvers (To) with every involved user in CC that the onboarding is waiting."""
    case = _case(session, case_id, user)
    info = waiting_info(session, case, user)
    if info is None:
        raise HTTPException(409, "This onboarding is not waiting for anyone's approval.")
    if info["last_reminder_at"]:
        elapsed = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - _naive(
            dt.datetime.fromisoformat(info["last_reminder_at"]))
        if elapsed < REMINDER_COOLDOWN:
            wait = int((REMINDER_COOLDOWN - elapsed).total_seconds() // 60) + 1
            raise HTTPException(409, f"A reminder was sent less than 10 minutes ago; try again in {wait} min.")
    to, cc = _recipients(session, case, info["roles"])
    if not to:
        names = " / ".join(ROLE_NAMES.get(r, r) for r in info["roles"])
        raise HTTPException(400, f"No active user has the {names} role for {case.ctry_cd}; ask an admin to add one.")
    url = get_settings(session).public_url
    text = (
        f"Hello,\n\nThe onboarding {case.code} — {case.title} ({case.ctry_cd}) is waiting for your action.\n\n"
        f"{info['message']}\n\n"
        + (f"Message from {user.name}:\n{body.message.strip()}\n\n" if body.message and body.message.strip() else "")
        + f"Open it here: {url}\n\nThis reminder was sent by {user.label} from the CCRE onboarding platform.\n"
    )
    note = send_email(session, kind="REMINDER", subject=f"[CCRE] Waiting for approval — {case.code} {case.ctry_cd}",
                      body=text, to=to, cc=cc, case_id=case.id, state=case.state, sent_by=user.label)
    _audit(session, case.id, user.label, "notification:reminder",
           {"to": to, "cc": cc, "status": note.status, "state": case.state})
    session.commit()
    return {"status": note.status, "to": to, "cc": cc, "error": note.error}


# --------------------------------------------------------------------------- #
# 3. DMG email — template (CCRE team) and per-onboarding task
# --------------------------------------------------------------------------- #

class DmgTemplateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)


class DmgEdit(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    to: Optional[list[str]] = None
    cc: Optional[list[str]] = None


class Decision(BaseModel):
    approve: bool
    comment: Optional[str] = None


class Reason(BaseModel):
    comment: str = Field(min_length=1)


def _dmg_out(task: Optional[DmgTask]) -> Optional[dict[str, Any]]:
    if task is None:
        return None
    return {"id": task.id, "status": task.status, "subject": task.subject, "body": task.body,
            "to": task.to, "cc": task.cc, "prepared_by": task.prepared_by, "submitted_by": task.submitted_by,
            "decided_by": task.decided_by, "decision_comment": task.decision_comment,
            "sent_at": task.sent_at.isoformat() if task.sent_at else None,
            "completed": task.status in ("SENT", "NOT_REQUIRED")}


def _addresses(values: list[str]) -> list[str]:
    try:
        return clean_addresses(values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/dmg/template", tags=["dmg"])
def dmg_template(_: CurrentUser = Depends(require_ccre), session: Session = Depends(get_session)) -> dict[str, Any]:
    tpl = get_template(session)
    session.commit()
    return {"subject": tpl.subject, "body": tpl.body, "to": tpl.to, "cc": tpl.cc, "placeholders": PLACEHOLDERS,
            "updated_by": tpl.updated_by}


@router.put("/dmg/template", tags=["dmg"])
def save_dmg_template(body: DmgTemplateIn, user: CurrentUser = Depends(require_ccre),
                      session: Session = Depends(get_session)) -> dict[str, Any]:
    unknown = unknown_placeholders(body.subject + body.body)
    if unknown:
        raise HTTPException(400, "Unknown placeholder(s): " + ", ".join("{{" + u + "}}" for u in unknown))
    tpl = get_template(session)
    tpl.subject, tpl.body = body.subject, body.body
    tpl.to, tpl.cc = _addresses(body.to), _addresses(body.cc)
    tpl.updated_by = user.label
    _audit(session, None, user.label, "dmg:template_saved", {"to": tpl.to, "cc": tpl.cc})
    session.commit()
    return dmg_template(user, session)


@router.get("/onboardings/{case_id}/dmg", tags=["dmg"])
def dmg_task(case_id: str, user: CurrentUser = Depends(require_internal),
             session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    tpl = get_template(session)
    session.commit()
    return {"task": _dmg_out(latest_dmg_task(session, case.id)),
            "template_ready": bool(tpl.to), "template_to": tpl.to}


def _editable_task(session: Session, case: OnboardingCase) -> DmgTask:
    _require_state(case, State.RULE_CONFIG)
    task = latest_dmg_task(session, case.id)
    if task is None:
        raise HTTPException(409, "Prepare the DMG email first.")
    return task


@router.post("/onboardings/{case_id}/dmg/prepare", tags=["dmg"])
def dmg_prepare(case_id: str, user: CurrentUser = Depends(require_ccre),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.RULE_CONFIG)
    task = latest_dmg_task(session, case.id)
    if task is not None and task.status in ("SENT", "IN_REVIEW"):
        raise HTTPException(409, f"The DMG email is already {task.status.lower().replace('_', ' ')}.")
    tpl = get_template(session)
    if not tpl.to:
        raise HTTPException(400, "Set the DMG recipients in the DMG email template first.")
    values = values_for(session, case, user.name)
    if task is None:
        task = DmgTask(case_id=case.id)
        session.add(task)
    task.status = "DRAFT"
    task.subject, task.body = fill(tpl.subject, values), fill(tpl.body, values)
    task.to, task.cc = list(tpl.to), list(tpl.cc)
    task.prepared_by, task.decided_by, task.decision_comment = user.label, None, None
    _audit(session, case.id, user.label, "dmg:prepared", {})
    session.commit()
    return _dmg_out(task)


@router.put("/onboardings/{case_id}/dmg", tags=["dmg"])
def dmg_edit(case_id: str, body: DmgEdit, user: CurrentUser = Depends(require_ccre),
             session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    task = _editable_task(session, case)
    if task.status != "DRAFT":
        raise HTTPException(409, "Only a draft can be edited.")
    if body.subject is not None:
        task.subject = body.subject
    if body.body is not None:
        task.body = body.body
    if body.to is not None:
        task.to = _addresses(body.to)
    if body.cc is not None:
        task.cc = _addresses(body.cc)
    session.commit()
    return _dmg_out(task)


@router.post("/onboardings/{case_id}/dmg/submit", tags=["dmg"])
def dmg_submit(case_id: str, user: CurrentUser = Depends(require_ccre),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    task = _editable_task(session, case)
    if task.status != "DRAFT":
        raise HTTPException(409, "Only a draft can be submitted for review.")
    if not task.to:
        raise HTTPException(400, "The DMG email has no recipient.")
    task.status, task.submitted_by = "IN_REVIEW", user.label
    _audit(session, case.id, user.label, "dmg:submitted", {})
    session.commit()
    return _dmg_out(task)


@router.post("/onboardings/{case_id}/dmg/decide", tags=["dmg"])
def dmg_decide(case_id: str, body: Decision, user: CurrentUser = Depends(require_ccre),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    """CCRE review: approve → the email is sent and the task is completed; reject → back to draft."""
    case = _case(session, case_id, user)
    task = _editable_task(session, case)
    if task.status != "IN_REVIEW":
        raise HTTPException(409, "The DMG email is not waiting for review.")
    if not user.dev and task.submitted_by == user.label:
        raise HTTPException(409, "A second CCRE team member must review the DMG email.")
    if not body.approve:
        if not (body.comment or "").strip():
            raise HTTPException(400, "Give a reason for rejecting the DMG email.")
        task.status, task.decided_by, task.decision_comment = "DRAFT", user.label, body.comment.strip()
        _audit(session, case.id, user.label, "dmg:rejected", {"comment": body.comment})
        session.commit()
        return _dmg_out(task)
    note = send_email(session, kind="DMG", subject=task.subject, body=task.body, to=task.to, cc=task.cc,
                      case_id=case.id, state=case.state, sent_by=user.label)
    if note.status == "FAILED":
        session.commit()
        raise HTTPException(502, f"Approved, but the email could not be sent: {note.error}")
    task.status, task.decided_by, task.decision_comment = "SENT", user.label, body.comment
    task.notification_id, task.sent_at = note.id, dt.datetime.now(dt.timezone.utc)
    _audit(session, case.id, user.label, "dmg:approved_and_sent", {"delivery": note.status, "to": task.to})
    session.commit()
    return _dmg_out(task)


@router.post("/onboardings/{case_id}/dmg/not-required", tags=["dmg"])
def dmg_not_required(case_id: str, body: Reason, user: CurrentUser = Depends(require(UserRole.CCRE_CONSULTANT,
                                                                                    UserRole.ADMIN)),
                     session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    _require_state(case, State.RULE_CONFIG)
    task = latest_dmg_task(session, case.id)
    if task is not None and task.status == "SENT":
        raise HTTPException(409, "The DMG email was already sent.")
    if task is None:
        task = DmgTask(case_id=case.id, subject="(not required)", body="")
        session.add(task)
    task.status, task.decided_by, task.decision_comment = "NOT_REQUIRED", user.label, body.comment.strip()
    _audit(session, case.id, user.label, "dmg:not_required", {"comment": body.comment})
    session.commit()
    return _dmg_out(task)


# --------------------------------------------------------------------------- #
# 4. sanity checklist
# --------------------------------------------------------------------------- #

# The sanity checklist lives in server/sanity_routes.py.


# --------------------------------------------------------------------------- #
# 5. UAT test cases — "+ scenario" (NLP) and row-by-row decisions
# --------------------------------------------------------------------------- #

class ScenarioIn(BaseModel):
    text: str = Field(min_length=5, max_length=4000)


class RowDecision(BaseModel):
    ids: list[str] = Field(default_factory=list)
    all_pending: bool = False
    approve: bool
    comment: Optional[str] = None


_SCENARIO_STATES = (State.RULE_CONFIG, State.SANITY_CHECK, State.UAT_TC_PREP, State.UAT_TC_REVIEW_CCRE,
                    State.UAT_TC_REVIEW_BUSINESS)


@router.post("/onboardings/{case_id}/uat/test-cases/scenario", tags=["uat"])
def add_scenario(case_id: str, body: ScenarioIn, user: CurrentUser = Depends(current_user),
                 session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """Convert a business scenario written in plain words into test case(s); they go through review."""
    case = _case(session, case_id, user)
    if user.is_business:
        _require_state(case, State.UAT_TC_REVIEW_BUSINESS)
    elif user.role in CCRE_ROLES:
        _require_state(case, *_SCENARIO_STATES)
    else:
        raise HTTPException(403, "Only the CCRE team or the business team add test scenarios.")
    rs = case_rule_set(session, case)
    if rs is None:
        raise HTTPException(409, "Start the M2C draft first — scenarios are tested against it.")
    rows = [r for r in _rule_rows(session, rs.id) if r["country"] == case.ctry_cd]
    suite = _advise(advisory.scenario_to_tests, rs.version, rows, body.text.strip())
    existing = set(session.execute(select(UatTestCase.test_id).where(UatTestCase.case_id == case.id)).scalars())
    created = []
    for i, c in enumerate(suite["cases"], start=1):
        test_id = c["test_id"]
        n = 1
        while test_id in existing:
            n += 1
            test_id = f"{c['test_id']}-{n}"
        existing.add(test_id)
        tc = UatTestCase(case_id=case.id, rule_set_id=rs.id, test_id=test_id, scenario=c["scenario"], kind=c["kind"],
                         business_summary=c.get("business_summary") or body.text.strip(),
                         preconditions=c.get("preconditions", []), input_conditions=c.get("input_conditions", []),
                         expected_requirement=c.get("expected_requirement"),
                         expected_case_created=bool(c.get("expected_case_created", True)),
                         validation_criteria=c.get("validation_criteria"), rule_coverage=c.get("rule_coverage", []),
                         priority=c.get("priority", "medium"), status="DRAFT", created_by=user.label)
        session.add(tc)
        created.append(tc)
    _audit(session, case.id, user.label, "uat:scenario_added", {"text": body.text, "cases": len(created)})
    session.commit()
    return [_test_case_out(tc, business=user.is_business) for tc in created]


@router.post("/onboardings/{case_id}/uat/test-cases/sample", tags=["uat"])
def add_sample_test_case(case_id: str, user: CurrentUser = Depends(current_user),
                         session: Session = Depends(get_session)) -> dict[str, Any]:
    """One complete test case built from the onboarding's own M2C row — no AI, nothing to type.

    A positive case: a shipment that meets every condition of the row must raise its requirement
    group. It is added as a normal row and goes through the same review as every other."""
    from tools.core.packages import active_package_version

    case = _case(session, case_id, user)
    if user.is_business:
        _require_state(case, State.UAT_TC_REVIEW_BUSINESS)
    elif user.role in CCRE_ROLES:
        _require_state(case, *_SCENARIO_STATES)
    else:
        raise HTTPException(403, "Only the CCRE team or the business team add test cases.")
    rs = case_rule_set(session, case)
    if rs is None:
        raise HTTPException(409, "Start the M2C draft first — the sample test case is built from its rows.")
    rules = list(session.execute(select(Rule).where(Rule.rule_set_id == rs.id, Rule.ctry_cd == case.ctry_cd)
                                 .order_by(Rule.row_no.is_(None), Rule.row_no)).scalars())
    rule = next((r for r in rules if r.sirg_cd), None)
    if rule is None:
        raise HTTPException(409, "The M2C draft has no row with a requirement group to test.")

    group, ctry = rule.sirg_cd, case.ctry_cd
    shipment = rule.shipment_type if rule.shipment_type in ("B2B", "B2C") else "B2C"
    conditions = [{"field": "destination_country", "operator": "equals", "value": ctry},
                  {"field": "shipment_type", "operator": "equals", "value": shipment}]
    value_text = ""
    if rule.min_value is not None or rule.max_value is not None:
        lo, hi = rule.min_value, rule.max_value
        value = (lo + 1 if lo is not None else 0) if hi is None else ((lo or 0) + hi) / 2
        value = round(value, 2)
        basis = "intrinsic_value" if rule.value_basis == "IV" else "declared_value"
        conditions += [{"field": basis, "operator": "equals", "value": str(value)},
                       {"field": "currency", "operator": "equals", "value": rule.currency or "EUR"}]
        value_text = f", {basis.replace('_', ' ')} {value} {rule.currency or 'EUR'}"
    if rule.min_weight is not None or rule.max_weight is not None:
        w = round((rule.min_weight or 0) + 0.5 if rule.max_weight is None
                  else ((rule.min_weight or 0) + rule.max_weight) / 2, 2)
        conditions.append({"field": "shipment_weight_kg", "operator": "equals", "value": str(w)})
        value_text += f", {w} kg"
    if rule.other_logic:
        conditions.append({"field": "other_logic", "operator": "equals", "value": rule.other_logic})
    row = f"row {rule.row_no}" if rule.row_no else "the new row"
    cmpt = ", ".join(b.cmpt_nm for b in rule.bindings if b.cmpt_nm) or group

    existing = set(session.execute(select(UatTestCase.test_id).where(UatTestCase.case_id == case.id)).scalars())
    n = 1
    while f"SAMPLE-{ctry}-{group}-{n:02d}" in existing:
        n += 1
    tc = UatTestCase(
        case_id=case.id, rule_set_id=rs.id, test_id=f"SAMPLE-{ctry}-{group}-{n:02d}", kind="positive",
        scenario=(f"{shipment} shipment to {ctry}{value_text}"
                  + (" that satisfies the Other Logic" if rule.other_logic else "")
                  + f" — meets every condition of M2C {row}, so CCRE raises {group}."),
        business_summary=f"A {shipment} shipment to {ctry} that meets the rule must be asked for {group}.",
        preconditions=[f"M2C draft {rs.version} loaded in UAT",
                       f"Config package {active_package_version(session) or '—'} active"],
        input_conditions=conditions, expected_requirement=group, expected_case_created=True,
        validation_criteria=f"A case is created and requirement {group} ({cmpt}) is raised for the shipment.",
        rule_coverage=[rule.id], priority="high", status="DRAFT", created_by=user.label)
    session.add(tc)
    _audit(session, case.id, user.label, "uat:sample_test_case_added", {"test_id": tc.test_id, "rule_row": rule.row_no})
    session.commit()
    return _test_case_out(tc, business=user.is_business)


@router.post("/onboardings/{case_id}/uat/test-cases/decide", tags=["uat"])
def decide_rows(case_id: str, body: RowDecision, user: CurrentUser = Depends(current_user),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    """Approve / reject test case rows. CCRE decides new rows; the business decides CCRE-approved rows."""
    case = _case(session, case_id, user)
    if not body.approve and not (body.comment or "").strip():
        raise HTTPException(400, "Give a reason for rejecting.")
    if user.is_business:
        _require_state(case, State.UAT_TC_REVIEW_BUSINESS)
        from_status, to_status = "CCRE_APPROVED", "BUSINESS_APPROVED"
    elif user.role in CCRE_ROLES:
        _require_state(case, *_SCENARIO_STATES)
        from_status, to_status = "DRAFT", "CCRE_APPROVED"
    else:
        raise HTTPException(403, "Only the CCRE team or the business team decide test cases.")
    stmt = select(UatTestCase).where(UatTestCase.case_id == case.id, UatTestCase.status == from_status)
    if not body.all_pending:
        if not body.ids:
            raise HTTPException(400, "Choose the test cases to decide.")
        stmt = stmt.where(UatTestCase.id.in_(body.ids))
    rows = list(session.execute(stmt).scalars())
    if not rows:
        raise HTTPException(409, "None of those test cases is waiting for your decision.")
    for tc in rows:
        tc.status = to_status if body.approve else "REJECTED"
        tc.review_comment = (body.comment or "").strip() or None if not body.approve else tc.review_comment
    _audit(session, case.id, user.label, "uat:test_cases_decided",
           {"decision": "approve" if body.approve else "reject", "by": str(user.role),
            "test_ids": [r.test_id for r in rows], "comment": body.comment})
    session.commit()
    return {"decided": len(rows), "status": to_status if body.approve else "REJECTED"}


@router.post("/uat/test-cases/{test_case_id}/reopen", tags=["uat"])
def reopen_row(test_case_id: str, user: CurrentUser = Depends(require_ccre),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    """Put a rejected row back for a new CCRE decision (e.g. after it was corrected)."""
    tc = session.get(UatTestCase, test_case_id)
    if tc is None:
        raise HTTPException(404, "No such test case.")
    case = _case(session, tc.case_id, user)
    _require_state(case, State.UAT_TC_PREP, State.UAT_TC_REVIEW_CCRE)
    if tc.status != "REJECTED":
        raise HTTPException(409, "Only a rejected test case can be reopened.")
    tc.status = "DRAFT"
    _audit(session, case.id, user.label, "uat:test_case_reopened", {"test_id": tc.test_id})
    session.commit()
    return _test_case_out(tc, business=False)
