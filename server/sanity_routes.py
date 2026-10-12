"""Sanity check routes — the guided checklist, its runs, waivers and the report."""
from __future__ import annotations

import datetime as dt
import io
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools import sanity
from tools.core.db import get_session
from tools.core.models import AuditEvent, OnboardingCase, SanityRun, SanityWaiver
from tools.workflow import State

from .auth import CurrentUser, ensure_country, require, require_ccre, require_internal
from tools.core.security import UserRole

router = APIRouter(tags=["sanity"])

EXPLANATION = ("The sanity check is the last gate before UAT test cases are written. It confirms the M2C rows "
               "are complete, say what the business asked for, pass validation, can be raised by the config "
               "package, and that the DMG email is done — so nobody writes or runs tests against a "
               "configuration that cannot work.")


class WaiverIn(BaseModel):
    item_key: str
    reason: str = Field(min_length=5, max_length=2000)
    reference: Optional[str] = Field(default=None, max_length=128)


def _case(session: Session, case_id: str, user: CurrentUser) -> OnboardingCase:
    case = session.get(OnboardingCase, case_id)
    if case is None:
        raise HTTPException(404, "No such onboarding.")
    ensure_country(user, case.ctry_cd)
    return case


def _run_out(r: SanityRun, current_fp: Optional[str] = None) -> dict[str, Any]:
    return {"id": r.id, "status": r.status, "passed": r.passed, "failed": r.failed, "waived": r.waived,
            "cycle": r.cycle, "run_by": r.run_by, "at": r.created_at.isoformat(),
            "current": current_fp is not None and r.fingerprint == current_fp}


@router.get("/onboardings/{case_id}/sanity")
def sanity_view(case_id: str, user: CurrentUser = Depends(require_internal),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    """The live checklist, the last saved run and whether it still applies."""
    case = _case(session, case_id, user)
    ev = sanity.evaluate(session, case)
    runs = list(session.execute(select(SanityRun).where(SanityRun.case_id == case.id)
                                .order_by(SanityRun.created_at.desc()).limit(20)).scalars())
    waivers = session.execute(select(SanityWaiver).where(SanityWaiver.case_id == case.id)
                              .order_by(SanityWaiver.created_at.desc())).scalars()
    in_stage = State(case.state) == State.SANITY_CHECK
    role = str(user.role)
    return {
        **ev,
        "explanation": EXPLANATION,
        "in_stage": in_stage,
        "latest_run": _run_out(runs[0], ev["fingerprint"]) if runs else None,
        "runs": [_run_out(r, ev["fingerprint"]) for r in runs],
        "waivers": [{"id": w.id, "item_key": w.item_key, "title": sanity.TITLES.get(w.item_key, w.item_key),
                     "reason": w.reason, "reference": w.reference, "by": w.waived_by,
                     "at": w.created_at.isoformat(), "revoked_by": w.revoked_by,
                     "revoked_at": w.revoked_at.isoformat() if w.revoked_at else None} for w in waivers],
        "can_run": in_stage and role in ("CCRE_TEAM", "CCRE_CONSULTANT", "ADMIN"),
        "can_waive": State(case.state) in (State.SANITY_CHECK, State.RULE_CONFIG)
        and role in ("CCRE_CONSULTANT", "ADMIN"),
        "approval_gap": sanity.approval_gap(session, case) if in_stage else None,
    }


@router.post("/onboardings/{case_id}/sanity/run")
def sanity_run(case_id: str, user: CurrentUser = Depends(require_ccre),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    if State(case.state) != State.SANITY_CHECK:
        raise HTTPException(409, "The sanity check runs while the onboarding is in the sanity check stage. "
                                 "Before that, the checklist is shown as a preview.")
    r = sanity.run(session, case, user.label)
    session.add(AuditEvent(case_id=case.id, actor=user.label, action="sanity:run",
                           detail={"run_id": r.id, "status": r.status, "failed": r.failed}))
    session.commit()
    return _run_out(r, r.fingerprint)


@router.post("/onboardings/{case_id}/sanity/waivers")
def add_waiver(case_id: str, body: WaiverIn,
               user: CurrentUser = Depends(require(UserRole.CCRE_CONSULTANT, UserRole.ADMIN)),
               session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    if State(case.state) not in (State.SANITY_CHECK, State.RULE_CONFIG):
        raise HTTPException(409, "Waivers are recorded during rule configuration or the sanity check.")
    if body.item_key not in sanity.WAIVABLE:
        raise HTTPException(400, "Only a package gap or a deliberate difference from the requirement can be "
                                 "waived. Everything else must be fixed.")
    item = next((i for i in sanity.evaluate(session, case)["items"] if i["key"] == body.item_key), None)
    if item is None or item["status"] not in ("fail",):
        raise HTTPException(409, "That check is not failing — nothing to waive.")
    w = SanityWaiver(case_id=case.id, item_key=body.item_key, reason=body.reason.strip(),
                     reference=(body.reference or "").strip() or None, waived_by=user.label)
    session.add(w)
    session.add(AuditEvent(case_id=case.id, actor=user.label, action="sanity:waived",
                           detail={"item": body.item_key, "reason": w.reason, "reference": w.reference}))
    session.flush()
    if State(case.state) == State.SANITY_CHECK:
        sanity.run(session, case, user.label)       # the waiver changes the result: record it
    session.commit()
    return {"id": w.id, "item_key": w.item_key}


@router.delete("/onboardings/{case_id}/sanity/waivers/{waiver_id}")
def revoke_waiver(case_id: str, waiver_id: str,
                  user: CurrentUser = Depends(require(UserRole.CCRE_CONSULTANT, UserRole.ADMIN)),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    case = _case(session, case_id, user)
    w = session.get(SanityWaiver, waiver_id)
    if w is None or w.case_id != case.id or w.revoked_at is not None:
        raise HTTPException(404, "No such active waiver.")
    w.revoked_by, w.revoked_at = user.label, dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    session.add(AuditEvent(case_id=case.id, actor=user.label, action="sanity:waiver_revoked",
                           detail={"item": w.item_key}))
    if State(case.state) == State.SANITY_CHECK:
        sanity.run(session, case, user.label)
    session.commit()
    return {"revoked": waiver_id}


@router.get("/onboardings/{case_id}/sanity/report.xlsx")
def sanity_report(case_id: str, run_id: Optional[str] = None, user: CurrentUser = Depends(require_internal),
                  session: Session = Depends(get_session)) -> Response:
    """The checklist as evidence: one sheet per run summary, findings and waivers."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    case = _case(session, case_id, user)
    r = session.get(SanityRun, run_id) if run_id else sanity.latest_run(session, case.id)
    if r is None or r.case_id != case.id:
        raise HTTPException(404, "No sanity check run yet.")
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="D40511")
    for row in (["Onboarding", case.code], ["Country", case.ctry_cd], ["Run", r.id], ["When", r.created_at.isoformat()],
                ["Run by", r.run_by], ["Correction cycle", r.cycle], ["Result", r.status],
                ["Passed / failed / waived", f"{r.passed} / {r.failed} / {r.waived}"], []):
        ws.append(row)
    ws.append(["Check", "Result", "Summary", "Waiver"])
    for c in ws[ws.max_row]:
        c.font, c.fill = head, fill
    for i in r.items:
        w = i.get("waiver") or {}
        ws.append([i["title"], i["status"].upper(), i["summary"],
                   f"{w.get('reason', '')} ({w.get('reference') or 'no ref'}) — {w.get('by', '')}" if w else ""])
    for col, width in zip("ABCD", (48, 10, 80, 60)):
        ws.column_dimensions[col].width = width
    fs = wb.create_sheet("Findings")
    fs.append(["Check", "Detail"])
    for c in fs[1]:
        c.font, c.fill = head, fill
    for i in r.items:
        for f in i.get("findings") or []:
            fs.append([i["title"], "; ".join(f"{k}: {v}" for k, v in f.items() if v not in (None, "", [], {}))])
    fs.column_dimensions["A"].width = 48
    fs.column_dimensions["B"].width = 140
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{case.code}_sanity_{r.created_at:%Y%m%d_%H%M}.xlsx"'})
