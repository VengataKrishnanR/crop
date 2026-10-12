"""Onboarding KPIs, computed from the audit trail and the stored artifacts.

Nothing here is entered by hand: every number is derived from transitions,
validation runs, UAT runs and milestone dates the platform already records.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from statistics import mean
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.core.db import get_session
from tools.core.models import (
    AuditEvent, Milestone, OnboardingCase, Rule, SanityRun, Timeline, UatRun, UatTestCase, ValidationRun,
)
from tools.timeline.planning import working_days_between
from tools.workflow import STATE_LABELS, State, stage_of
from tools.workflow.case_facts import case_rule_set

from .auth import CurrentUser, require_internal

router = APIRouter()

_REVIEW_STATES = (State.REQUIREMENT_REVIEW, State.TIMELINE_REVIEW, State.UAT_TC_REVIEW_CCRE,
                  State.UAT_TC_REVIEW_BUSINESS, State.UAT_RESULT_REVIEW, State.UAT_SIGNOFF)
_CCRE_RETURNS = {"return_requirement", "sanity_failed", "ccre_return_test_cases", "request_correction"}
_BUSINESS_RETURNS = {"business_return_test_cases", "business_reject_results"}


def _naive(value: dt.datetime) -> dt.datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _days(delta: dt.timedelta) -> float:
    return round(delta.total_seconds() / 86400, 2)


def _avg(values: list[float]) -> Optional[float]:
    return round(mean(values), 2) if values else None


def _pct(part: int, whole: int) -> Optional[float]:
    return round(100.0 * part / whole, 1) if whole else None


def compute_kpis(session: Session) -> dict[str, Any]:
    cases = list(session.execute(select(OnboardingCase)).scalars())
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    time_in_state: dict[str, list[float]] = defaultdict(list)
    review_waits: list[float] = []
    lead_times: list[float] = []
    cycles: list[int] = []
    ccre_defects = business_defects = 0
    ftr_hits = ftr_total = 0
    first_pass = first_total = 0
    covered_rules = total_rules = 0
    slips: list[int] = []
    on_time = finished_milestones = 0
    by_stage: dict[str, int] = defaultdict(int)
    rows = []

    for case in cases:
        state = State(case.state)
        stage = stage_of(state)
        by_stage[stage.label if stage else STATE_LABELS[state]] += 1

        events = list(session.execute(
            select(AuditEvent).where(AuditEvent.case_id == case.id, AuditEvent.action.like("transition:%"))
            .order_by(AuditEvent.at, AuditEvent.id)).scalars())
        entered_at = _naive(case.created_at) if case.created_at else now
        current = State.INTAKE
        corrections = 0
        completed_at: Optional[dt.datetime] = None
        for ev in events:
            at = _naive(ev.at)
            spent = _days(at - entered_at)
            time_in_state[str(current)].append(spent)
            if current in _REVIEW_STATES:
                review_waits.append(spent)
            name = ev.action.split(":", 1)[1]
            if name == "request_correction":
                corrections += 1
            if name in _CCRE_RETURNS:
                ccre_defects += 1
            if name in _BUSINESS_RETURNS:
                business_defects += 1
            current = State(ev.detail.get("to", str(current)))
            entered_at = at
            if current == State.COMPLETED:
                completed_at = at
        if completed_at and case.created_at:
            lead_times.append(_days(completed_at - _naive(case.created_at)))
        cycles.append(1 + corrections)

        # First time right: the first sanity check run passed (older onboardings: the first validation run).
        first_sanity = session.execute(
            select(SanityRun).where(SanityRun.case_id == case.id)
            .order_by(SanityRun.created_at).limit(1)).scalar_one_or_none()
        first_validation = None if first_sanity else session.execute(
            select(ValidationRun).where(ValidationRun.case_id == case.id)
            .order_by(ValidationRun.at).limit(1)).scalar_one_or_none()
        if first_sanity is not None:
            ftr_total += 1
            ftr_hits += int(first_sanity.status == "PASS")
        elif first_validation is not None:
            ftr_total += 1
            ftr_hits += int(first_validation.blocker_count == 0)

        first_run = session.execute(
            select(UatRun).where(UatRun.case_id == case.id, UatRun.status == "COMPLETED")
            .order_by(UatRun.started_at).limit(1)).scalar_one_or_none()
        if first_run is not None:
            executed = first_run.passed + first_run.failed + first_run.errors
            first_total += executed
            first_pass += first_run.passed

        coverage = None
        rs = case_rule_set(session, case)
        if rs is not None:
            rule_ids = set(session.execute(select(Rule.id).where(Rule.rule_set_id == rs.id,
                                                                  Rule.ctry_cd == case.ctry_cd)).scalars())
            covered: set[str] = set()
            for tc in session.execute(select(UatTestCase).where(UatTestCase.case_id == case.id,
                                                                UatTestCase.status != "REJECTED")).scalars():
                covered |= set(tc.rule_coverage or []) & rule_ids
            if rule_ids:
                total_rules += len(rule_ids)
                covered_rules += len(covered)
                coverage = _pct(len(covered), len(rule_ids))

        approved = session.execute(
            select(Timeline).where(Timeline.case_id == case.id, Timeline.status == "APPROVED")
            .order_by(Timeline.version.desc()).limit(1)).scalar_one_or_none()
        case_slip = None
        planned_rtp = None
        if approved is not None:
            planned_rtp = max((m.planned_end for m in approved.milestones), default=None)
            for m in session.execute(select(Milestone).where(Milestone.timeline_id == approved.id)).scalars():
                if m.actual_end:
                    finished_milestones += 1
                    slip = working_days_between(m.planned_end, m.actual_end)
                    slips.append(slip)
                    on_time += int(slip <= 0)
                    case_slip = slip

        rows.append({
            "id": case.id, "code": case.code, "country": case.ctry_cd, "state": str(state),
            "state_label": STATE_LABELS[state], "cycles": 1 + corrections,
            "first_run_pass_rate": _pct(first_run.passed, first_run.passed + first_run.failed + first_run.errors)
            if first_run else None,
            "rule_coverage_pct": coverage,
            "latest_milestone_slip_days": case_slip,
            "planned_rtp": planned_rtp.isoformat() if planned_rtp else None,
        })

    return {
        "summary": {
            "onboardings": len(cases),
            "completed": sum(1 for c in cases if c.state == State.COMPLETED),
            "avg_lead_time_days": _avg(lead_times),
            "schedule_on_time_pct": _pct(on_time, finished_milestones),
            "avg_milestone_slip_working_days": _avg([float(s) for s in slips]),
            "m2c_first_time_right_pct": _pct(ftr_hits, ftr_total),
            "avg_correction_cycles": _avg([float(c) for c in cycles]),
            "first_run_pass_rate_pct": _pct(first_pass, first_total),
            "rule_coverage_pct": _pct(covered_rules, total_rules),
            "defects_found_by_ccre": ccre_defects,
            "defects_found_by_business": business_defects,
            "avg_review_wait_days": _avg(review_waits),
        },
        "by_stage": dict(by_stage),
        "avg_days_in_state": {STATE_LABELS[State(k)]: _avg(v) for k, v in time_in_state.items()},
        "cases": rows,
        "definitions": {
            "avg_lead_time_days": "Calendar days from onboarding created to completed (completed onboardings only).",
            "schedule_on_time_pct": "Share of finished milestones that ended on or before the approved plan.",
            "avg_milestone_slip_working_days": "Average working days a finished milestone ended after plan (negative = early).",
            "m2c_first_time_right_pct": "Share of onboardings whose first sanity check run passed.",
            "avg_correction_cycles": "UAT cycles per onboarding (1 = no M2C correction needed).",
            "first_run_pass_rate_pct": "Test cases passing in each onboarding's first UAT run.",
            "rule_coverage_pct": "M2C rules referenced by at least one non-rejected UAT test case.",
            "defects_found_by_ccre": "Returns and corrections raised by the CCRE side.",
            "defects_found_by_business": "Returns raised by the business team.",
            "avg_review_wait_days": "Average time a case waited in a review / approval state.",
        },
    }


@router.get("/kpis", tags=["kpis"])
def kpis(_: CurrentUser = Depends(require_internal),
         session: Session = Depends(get_session)) -> dict[str, Any]:
    return compute_kpis(session)
