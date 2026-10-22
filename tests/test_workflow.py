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
        ("approve_timeline", State.RULE_CONFIG),
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
    # TIMELINE_REVIEW is only left for onboardings that reached it under the earlier flow;
    # new onboardings go straight from planning to rule configuration (the PM approves).
    assert targets | {State.TIMELINE_REVIEW} == set(State)
    assert workflow.transitions_from(State.TIMELINE_REVIEW)              # they can still finish
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


def test_sanity_needs_a_passing_current_run_and_the_dmg_task() -> None:
    t = workflow.find_transition(State.SANITY_CHECK, "sanity_passed")
    gap = workflow.gate_reasons(t, GateContext(has_rule_set=True, dmg_complete=True,
                                               sanity_gap="Run the sanity check first."))
    assert gap == ["Run the sanity check first."]
    assert workflow.gate_reasons(t, GateContext(has_rule_set=True, dmg_complete=True)) == []
    assert any("DMG" in r for r in workflow.gate_reasons(t, GateContext(has_rule_set=True)))


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


def test_reject_needs_a_reason(session: Session) -> None:
    case = _case(session, State.REQUIREMENT_REVIEW)
    with pytest.raises(workflow.TransitionError, match="needs a reason"):
        workflow.fire(session, case, "return_requirement", actor="c", actor_role=Role.CCRE_CONSULTANT)


def test_every_stage_has_an_approve_and_a_reject() -> None:
    for state in (State.REQUIREMENT_REVIEW, State.TIMELINE_REVIEW, State.SANITY_CHECK, State.UAT_TC_REVIEW_CCRE,
                  State.UAT_TC_REVIEW_BUSINESS, State.UAT_RESULT_REVIEW, State.UAT_SIGNOFF):
        kinds = {t.kind for t in workflow.transitions_from(state)}
        assert {"approve", "reject"} <= kinds, state


def test_waiting_roles_name_who_must_act() -> None:
    assert workflow.waiting_roles(State.REQUIREMENT_REVIEW) == ["CCRE_CONSULTANT"]
    assert workflow.waiting_roles(State.TIMELINE_REVIEW) == ["PM"]
    assert workflow.waiting_roles(State.UAT_SIGNOFF) == ["BUSINESS"]
    assert workflow.waiting_roles(State.UAT_EXECUTION) == ["CCRE_TEAM"]


def test_dmg_and_row_reviews_gate_the_stages() -> None:
    submit = workflow.find_transition(State.RULE_CONFIG, "request_sanity_check")
    assert any("DMG" in r for r in workflow.gate_reasons(submit, GateContext(has_rule_set=True)))
    ccre = workflow.find_transition(State.UAT_TC_REVIEW_CCRE, "ccre_approve_test_cases")
    pending = GateContext(test_cases_ready=3, tc_pending_ccre=1, tc_ccre_approved=2)
    assert any("still need a CCRE" in r for r in workflow.gate_reasons(ccre, pending))
    biz = workflow.find_transition(State.UAT_TC_REVIEW_BUSINESS, "business_approve_test_cases")
    waiting = GateContext(test_cases_ready=2, tc_ccre_approved=1, tc_business_approved=1)
    assert any("business approve" in r for r in workflow.gate_reasons(biz, waiting))
    assert workflow.gate_reasons(biz, GateContext(test_cases_ready=2, tc_business_approved=2)) == []
