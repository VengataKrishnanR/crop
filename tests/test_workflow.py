"""Lifecycle state machine — structure, roles and gates (no HTTP, no agents)."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from tools.core.models import Approval, AuditEvent, OnboardingCase
from tools.validation import ValidationReport
from tools.validation.report import Finding
from tools.workflow import state_machine as workflow
from tools.workflow.state_machine import GateContext, Role, State

pytestmark = pytest.mark.workflow


def _case(session: Session, state: State) -> OnboardingCase:
    case = OnboardingCase(code=f"T-{state}", ctry_cd="DE", title="t", state=str(state))
    session.add(case)
    session.commit()
    return case


def _clean() -> ValidationReport:
    return ValidationReport(findings=[], checks_run=["CHK001"])


def _dirty() -> ValidationReport:
    return ValidationReport(findings=[Finding(code="CHK015", severity="blocker", where="x", message="m")],
                            checks_run=["CHK015"])


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #

def test_sequence_follows_the_onboarding_order() -> None:
    """Intake → requirement → timeline → rule config → sanity → UAT prep → reviews → execution → sign-off → RTP."""
    path = [
        ("submit_requirement", State.REQUIREMENT_REVIEW), ("approve_requirement", State.TIMELINE_PLANNING),
        ("submit_timeline", State.TIMELINE_REVIEW), ("approve_timeline", State.RULE_CONFIG),
        ("request_sanity_check", State.SANITY_CHECK), ("sanity_passed", State.UAT_TC_PREP),
        ("submit_test_cases", State.UAT_TC_REVIEW_CCRE),
        ("ccre_approve_test_cases", State.UAT_TC_REVIEW_BUSINESS),
        ("business_approve_test_cases", State.UAT_EXECUTION),
        ("complete_execution", State.UAT_RESULT_REVIEW), ("ccre_accept_results", State.UAT_SIGNOFF),
        ("business_signoff", State.RTP), ("confirm_production", State.COMPLETED),
    ]
    state = State.INTAKE
    for name, target in path:
        t = workflow.find_transition(state, name)
        assert t is not None, f"{name} missing from {state}"
        assert t.target == target
        state = target


def test_ccre_consultant_approves_the_requirement_not_the_pm() -> None:
    t = workflow.find_transition(State.REQUIREMENT_REVIEW, "approve_requirement")
    assert t.actors == frozenset({Role.CCRE_CONSULTANT})


def test_pm_approves_the_timeline() -> None:
    t = workflow.find_transition(State.TIMELINE_REVIEW, "approve_timeline")
    assert t.actors == frozenset({Role.PM})


def test_test_cases_are_reviewed_by_ccre_before_business() -> None:
    ccre = workflow.find_transition(State.UAT_TC_REVIEW_CCRE, "ccre_approve_test_cases")
    assert ccre.target == State.UAT_TC_REVIEW_BUSINESS
    assert Role.BUSINESS not in ccre.actors
    business = workflow.find_transition(State.UAT_TC_REVIEW_BUSINESS, "business_approve_test_cases")
    assert business.actors == frozenset({Role.BUSINESS})


def test_failed_results_loop_back_to_rule_config() -> None:
    t = workflow.find_transition(State.UAT_RESULT_REVIEW, "request_correction")
    assert t.target == State.RULE_CONFIG


def test_results_go_to_ccre_before_business() -> None:
    accept = workflow.find_transition(State.UAT_RESULT_REVIEW, "ccre_accept_results")
    assert Role.BUSINESS not in accept.actors and accept.target == State.UAT_SIGNOFF
    signoff = workflow.find_transition(State.UAT_SIGNOFF, "business_signoff")
    assert signoff.actors == frozenset({Role.BUSINESS})


def test_the_system_can_never_move_into_an_approved_state() -> None:
    for t in workflow.TRANSITIONS:
        if Role.SYSTEM in t.actors:
            assert t.target not in workflow.APPROVED_STATES, t.name


def test_every_state_is_reachable_and_labelled() -> None:
    targets = {t.target for t in workflow.TRANSITIONS} | {State.INTAKE}
    assert targets == set(State)
    assert set(workflow.STATE_LABELS) == set(State)
    staged = {s for stage in workflow.STAGES for s in stage.states}
    assert staged | {State.WITHDRAWN} == set(State)


def test_terminal_states_have_no_exit() -> None:
    for state in workflow.TERMINAL_STATES:
        assert workflow.transitions_from(state) == []


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #

def test_requirement_must_exist_before_submission() -> None:
    t = workflow.find_transition(State.INTAKE, "submit_requirement")
    assert workflow.gate_reasons(t, GateContext())
    assert workflow.gate_reasons(t, GateContext(has_requirement=True)) == []


def test_sanity_needs_clean_validation_and_complete_package() -> None:
    t = workflow.find_transition(State.SANITY_CHECK, "sanity_passed")
    assert any("not been run" in r for r in workflow.gate_reasons(t, GateContext(has_rule_set=True)))
    blocked = workflow.gate_reasons(t, GateContext(has_rule_set=True, report=_dirty(), package_complete=True))
    assert any("blocking finding" in r for r in blocked)
    no_pkg = workflow.gate_reasons(t, GateContext(has_rule_set=True, report=_clean(), package_complete=False))
    assert any("package" in r for r in no_pkg)
    assert workflow.gate_reasons(t, GateContext(has_rule_set=True, report=_clean(), package_complete=True)) == []


def test_results_need_complete_execution_and_passing_tests() -> None:
    t = workflow.find_transition(State.UAT_RESULT_REVIEW, "ccre_accept_results")
    assert workflow.gate_reasons(t, GateContext(execution_complete=True, tests_total=0))
    failing = GateContext(execution_complete=True, tests_total=3, tests_passed=2, tests_failed=1)
    assert any("1 of 3" in r for r in workflow.gate_reasons(t, failing))
    passing = GateContext(execution_complete=True, tests_total=3, tests_passed=3)
    assert workflow.gate_reasons(t, passing) == []


# --------------------------------------------------------------------------- #
# firing
# --------------------------------------------------------------------------- #

def test_wrong_role_is_refused(session: Session) -> None:
    case = _case(session, State.REQUIREMENT_REVIEW)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(session, case, "approve_requirement", actor="p", actor_role=Role.PM,
                      ctx=GateContext(has_requirement=True))
    assert any("CCRE_CONSULTANT" in r for r in exc.value.reasons)
    assert case.state == State.REQUIREMENT_REVIEW


def test_system_cannot_complete_execution_into_approval(session: Session) -> None:
    case = _case(session, State.UAT_SIGNOFF)
    with pytest.raises(workflow.TransitionError):
        workflow.fire(session, case, "business_signoff", actor="system", actor_role=Role.SYSTEM,
                      ctx=GateContext(tests_total=1, tests_passed=1))


def test_unavailable_transition_lists_what_is_possible(session: Session) -> None:
    case = _case(session, State.INTAKE)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(session, case, "business_signoff", actor="b", actor_role=Role.BUSINESS)
    assert "submit_requirement" in exc.value.reasons[0]


def test_decisions_are_recorded_with_the_right_verdict(session: Session) -> None:
    case = _case(session, State.REQUIREMENT_REVIEW)
    workflow.fire(session, case, "return_requirement", actor="c", actor_role=Role.CCRE_CONSULTANT, comment="unclear")
    workflow.fire(session, case, "submit_requirement", actor="b", actor_role=Role.BUSINESS,
                  ctx=GateContext(has_requirement=True))
    workflow.fire(session, case, "approve_requirement", actor="c", actor_role=Role.CCRE_CONSULTANT,
                  ctx=GateContext(has_requirement=True))
    session.commit()
    decisions = [a.decision for a in session.query(Approval).order_by(Approval.at, Approval.id)]
    assert decisions == ["REJECTED", "SUBMITTED", "APPROVED"]
    assert case.state == State.TIMELINE_PLANNING


def test_system_moves_are_audited_but_not_approvals(session: Session) -> None:
    case = _case(session, State.UAT_EXECUTION)
    workflow.fire(session, case, "complete_execution", actor="system", actor_role=Role.SYSTEM,
                  ctx=GateContext(execution_complete=True))
    session.commit()
    assert session.query(Approval).count() == 0
    assert session.query(AuditEvent).filter(AuditEvent.action == "transition:complete_execution").count() == 1


def test_correction_loop_restarts_at_rule_config(session: Session) -> None:
    case = _case(session, State.UAT_RESULT_REVIEW)
    workflow.fire(session, case, "request_correction", actor="t", actor_role=Role.CCRE_TEAM,
                  comment="BG-IOSS-01 failed")
    assert case.state == State.RULE_CONFIG
