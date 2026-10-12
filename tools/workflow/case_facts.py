"""Per-case facts the lifecycle gates are evaluated on, and the case M2C draft.

Gate facts are always recomputed from the database at the moment a transition is
requested — nothing is cached, nothing is taken from the caller's word.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from tools.core.models import (
    AuditEvent, DmgTask, OnboardingCase, Requirement, Rule, RuleBinding, RuleSet, Timeline, UatResult,
    UatRun, UatTestCase,
)
from tools.validation import load_snapshot, run_checks, validate_rule_set

from .state_machine import GateContext

_PACKAGE_CHECKS = ["CHK002", "CHK003", "CHK015"]


# --------------------------------------------------------------------------- #
# M2C draft (the case's own rule set)
# --------------------------------------------------------------------------- #

def case_rule_set(session: Session, case: OnboardingCase) -> Optional[RuleSet]:
    """The case's working M2C draft: its newest rule set."""
    return session.execute(
        select(RuleSet).where(RuleSet.case_id == case.id).order_by(RuleSet.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def baseline_rule_set(session: Session, country: Optional[str] = None) -> Optional[RuleSet]:
    """The newest workbook rule set not owned by a case (what ``ccre bootstrap`` loads)."""
    stmt = select(RuleSet).where(RuleSet.case_id.is_(None)).order_by(RuleSet.created_at.desc())
    if country:
        stmt = stmt.where(RuleSet.id.in_(select(Rule.rule_set_id).where(Rule.ctry_cd == country.upper())))
    return session.execute(stmt.limit(1)).scalar_one_or_none()


def start_m2c_draft(session: Session, case: OnboardingCase, actor: str) -> tuple[RuleSet, int]:
    """Create the case's M2C draft, seeded with the country's existing workbook rows.

    Returns the rule set and how many rules were copied. Idempotent: an existing
    draft is returned unchanged.
    """
    existing = case_rule_set(session, case)
    if existing is not None:
        count = session.execute(
            select(func.count()).select_from(Rule).where(Rule.rule_set_id == existing.id)
        ).scalar_one()
        return existing, count

    baseline = baseline_rule_set(session, case.ctry_cd)
    draft = RuleSet(
        case_id=case.id, version="v0.1", label=f"{case.ctry_cd} M2C draft", created_by=actor,
        source_version=baseline.source_version if baseline else None, sealed=False,
    )
    session.add(draft)
    session.flush()

    copied = 0
    if baseline is not None:
        rules = session.execute(
            select(Rule).where(Rule.rule_set_id == baseline.id, Rule.ctry_cd == case.ctry_cd)
            .options(selectinload(Rule.bindings)).order_by(Rule.row_no)
        ).scalars()
        for rule in rules:
            copy = Rule(
                rule_set_id=draft.id, row_no=rule.row_no, direction=rule.direction, region=rule.region,
                ctry_cd=rule.ctry_cd, shipment_type=rule.shipment_type,
                effective_date=rule.effective_date, expiry_date=rule.expiry_date,
                network_product_codes=rule.network_product_codes, value_basis=rule.value_basis,
                currency=rule.currency, min_value=rule.min_value, max_value=rule.max_value,
                min_weight=rule.min_weight, max_weight=rule.max_weight, other_logic=rule.other_logic,
                country_hold_cd=rule.country_hold_cd, global_hold_cd=rule.global_hold_cd,
                sirg_cd=rule.sirg_cd, doc_reference=rule.doc_reference,
            )
            session.add(copy)
            session.flush()
            for b in rule.bindings:
                session.add(RuleBinding(
                    rule_id=copy.id, sirg_cd=b.sirg_cd, sirg_id=b.sirg_id, sir_id=b.sir_id,
                    cmpt_nm=b.cmpt_nm, waived_if_whitelisted=b.waived_if_whitelisted,
                    waived_to_validate=b.waived_to_validate, check_service_code=b.check_service_code,
                    attribute_ids=list(b.attribute_ids or []),
                ))
            copied += 1
    session.add(AuditEvent(case_id=case.id, actor=actor, action="m2c:draft_started",
                           detail={"rule_set_id": draft.id, "rules_copied": copied,
                                   "baseline": baseline.id if baseline else None}))
    session.flush()
    return draft, copied


# --------------------------------------------------------------------------- #
# facts
# --------------------------------------------------------------------------- #

def latest_requirement(session: Session, case_id: str) -> Optional[Requirement]:
    return session.execute(
        select(Requirement).where(Requirement.case_id == case_id)
        .order_by(Requirement.version.desc()).limit(1)
    ).scalar_one_or_none()


def current_timeline(session: Session, case_id: str) -> Optional[Timeline]:
    return session.execute(
        select(Timeline).where(Timeline.case_id == case_id, Timeline.status != "SUPERSEDED")
        .options(selectinload(Timeline.milestones))
        .order_by(Timeline.version.desc()).limit(1)
    ).scalar_one_or_none()


def latest_dmg_task(session: Session, case_id: str) -> Optional[DmgTask]:
    return session.execute(
        select(DmgTask).where(DmgTask.case_id == case_id).order_by(DmgTask.updated_at.desc()).limit(1)
    ).scalar_one_or_none()


def correction_cycle(session: Session, case_id: str) -> int:
    """1 for the first UAT cycle; +1 for every correction sent back to rule config."""
    loops = session.execute(
        select(func.count()).select_from(AuditEvent)
        .where(AuditEvent.case_id == case_id, AuditEvent.action == "transition:request_correction")
    ).scalar_one()
    return 1 + int(loops)


def latest_run(session: Session, case_id: str, cycle: Optional[int] = None) -> Optional[UatRun]:
    stmt = select(UatRun).where(UatRun.case_id == case_id, UatRun.status == "COMPLETED")
    if cycle is not None:
        stmt = stmt.where(UatRun.cycle == cycle)
    return session.execute(stmt.order_by(UatRun.started_at.desc()).limit(1)).scalar_one_or_none()


def executable_test_cases(session: Session, case_id: str) -> list[UatTestCase]:
    return list(session.execute(
        select(UatTestCase).where(UatTestCase.case_id == case_id,
                                  UatTestCase.status == "BUSINESS_APPROVED")
        .order_by(UatTestCase.test_id)
    ).scalars())


def gate_context(session: Session, case: OnboardingCase) -> GateContext:
    ctx = GateContext()
    req = latest_requirement(session, case.id)
    ctx.has_requirement = req is not None
    if req is not None:
        chk = (req.structured or {}).get("m2c_check")
        if chk is None:
            ctx.requirement_gaps = ["the M2C criteria (region, B2B/B2C, dates, product codes, value, weight, "
                                    "other logic)"]
        else:
            from tools.intake_fields import LABELS
            ctx.requirement_gaps = [m["label"] for m in chk.get("missing", [])] + [
                f"{LABELS.get(k, k)} ({v})" for k, v in (chk.get("errors") or {}).items()]
    ctx.has_timeline = current_timeline(session, case.id) is not None

    rule_set = case_rule_set(session, case)
    if rule_set is not None:
        ctx.has_rule_set = True
        ctx.report, _ = validate_rule_set(session, rule_set.id, case_id=case.id, persist=False)
        snapshot = load_snapshot(session, rule_set_id=rule_set.id)
        ctx.package_complete = run_checks(snapshot, only=_PACKAGE_CHECKS).is_clean
        from tools.ruleconfig import draft_row_errors
        ctx.rows_with_errors = draft_row_errors(session, case, rule_set)

    counts = dict(session.execute(
        select(UatTestCase.status, func.count()).where(UatTestCase.case_id == case.id)
        .group_by(UatTestCase.status)).all())
    ctx.test_cases_ready = sum(n for s, n in counts.items() if s != "REJECTED")
    ctx.tc_pending_ccre = counts.get("DRAFT", 0)
    ctx.tc_ccre_approved = counts.get("CCRE_APPROVED", 0)
    ctx.tc_business_approved = counts.get("BUSINESS_APPROVED", 0)

    dmg = latest_dmg_task(session, case.id)
    ctx.dmg_complete = dmg is not None and dmg.status in ("SENT", "NOT_REQUIRED")

    run = latest_run(session, case.id, correction_cycle(session, case.id))
    if run is not None:
        results = list(session.execute(select(UatResult).where(UatResult.run_id == run.id)).scalars())
        executed = {r.test_case_id for r in results}
        expected = {tc.id for tc in executable_test_cases(session, case.id)}
        ctx.execution_complete = bool(expected) and expected <= executed
        ctx.tests_total = len(results)
        ctx.tests_passed = sum(1 for r in results if r.verdict == "PASS")
        ctx.tests_failed = ctx.tests_total - ctx.tests_passed
    return ctx
