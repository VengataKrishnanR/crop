"""Workflow and gate tests.

The properties asserted here are the governance model. If one of these breaks,
the platform has stopped being safe to point at a customs system.
"""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from tools.workflow import state_machine as workflow
from tools.core.models import Approval, AuditEvent, OnboardingCase
from tools.validation import ValidationReport
from tools.validation.report import Finding

from conftest import add_rule, make_rule_set


def _clean() -> ValidationReport:
    return ValidationReport(findings=[], checks_run=["CHK001"])


def _blocked(n: int = 1) -> ValidationReport:
    return ValidationReport(
        findings=[
            Finding(code=f"CHK00{i}", severity="blocker", where="rules", message="broken")
            for i in range(n)
        ],
        checks_run=["CHK001"],
    )


def _cautioned() -> ValidationReport:
    return ValidationReport(
        findings=[Finding(code="CHK012", severity="caution", where="rules", message="odd currency")],
        checks_run=["CHK012"],
    )


# --------------------------------------------------------------------------- #
# Structural properties
# --------------------------------------------------------------------------- #

def test_the_system_can_never_advance_into_an_approved_state_ungated() -> None:
    """The central invariant: code may block, only people may approve."""
    for transition in workflow.TRANSITIONS:
        if transition.actor == workflow.Role.SYSTEM and transition.target in workflow.APPROVED_STATES:
            assert transition.requires_clean_validation, (
                f"{transition.name} lets the system enter {transition.target} with no gate"
            )


def test_rfc_states_are_absent() -> None:
    """RFC/ServiceNow is out of scope, so no state or transition mentions it."""
    names = {str(s) for s in workflow.State}
    assert not any("RFC" in n for n in names)
    assert not any("rfc" in t.name for t in workflow.TRANSITIONS)


def test_every_transition_target_is_reachable_and_declared() -> None:
    states = {str(s) for s in workflow.State}
    for transition in workflow.TRANSITIONS:
        assert str(transition.source) in states
        assert str(transition.target) in states


def test_terminal_states_have_no_exit() -> None:
    for state in (workflow.State.COMPLETED, workflow.State.WITHDRAWN):
        assert workflow.transitions_from(state) == []


# --------------------------------------------------------------------------- #
# Gate behaviour
# --------------------------------------------------------------------------- #

def test_support_signoff_is_blocked_by_a_blocker(session: Session, bg_case: OnboardingCase) -> None:
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    ctx = workflow.GateContext(report=_blocked(3), package_complete=True)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "support_signoff", actor="syahidah",
            actor_role=workflow.Role.SUPPORT, ctx=ctx,
        )
    assert "3 blocking findings" in " ".join(exc.value.reasons)
    assert bg_case.state == str(workflow.State.SUPPORT_REVIEW)


def test_support_signoff_is_blocked_by_an_incomplete_package(
    session: Session, bg_case: OnboardingCase
) -> None:
    """The BG situation: rules are clean but the package has no BG rows."""
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    ctx = workflow.GateContext(report=_clean(), package_complete=False)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "support_signoff", actor="syahidah",
            actor_role=workflow.Role.SUPPORT, ctx=ctx,
        )
    assert any("config package" in r for r in exc.value.reasons)


def test_cautions_alone_do_not_block_signoff(session: Session, bg_case: OnboardingCase) -> None:
    """Cautions are accepted by the signer, not fixed by the system."""
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    ctx = workflow.GateContext(report=_cautioned(), package_complete=True)
    workflow.fire(
        session, bg_case, "support_signoff", actor="syahidah",
        actor_role=workflow.Role.SUPPORT, ctx=ctx, comment="BGN accepted",
    )
    assert bg_case.state == str(workflow.State.TEST_READY)


def test_validation_must_have_been_run(session: Session, bg_case: OnboardingCase) -> None:
    """A gate with no report is closed, not open. Absence is not success."""
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    ctx = workflow.GateContext(report=None, package_complete=True)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "support_signoff", actor="x",
            actor_role=workflow.Role.SUPPORT, ctx=ctx,
        )
    assert any("has not been run" in r for r in exc.value.reasons)


def test_wrong_role_is_refused(session: Session, bg_case: OnboardingCase) -> None:
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    ctx = workflow.GateContext(report=_clean(), package_complete=True)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "support_signoff", actor="artur",
            actor_role=workflow.Role.COUNTRY, ctx=ctx,
        )
    assert any("Only SUPPORT" in r for r in exc.value.reasons)


def test_country_signoff_requires_passing_tests(session: Session, bg_case: OnboardingCase) -> None:
    bg_case.state = str(workflow.State.COUNTRY_SIGNOFF)
    session.commit()
    ctx = workflow.GateContext(tests_total=12, tests_passed=10, tests_failed=2)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "country_accepts", actor="artur",
            actor_role=workflow.Role.COUNTRY, ctx=ctx,
        )
    assert any("2 of 12 tests failed" in r for r in exc.value.reasons)


def test_zero_tests_is_not_passing(session: Session, bg_case: OnboardingCase) -> None:
    bg_case.state = str(workflow.State.COUNTRY_SIGNOFF)
    session.commit()
    ctx = workflow.GateContext(tests_total=0)
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "country_accepts", actor="artur",
            actor_role=workflow.Role.COUNTRY, ctx=ctx,
        )
    assert any("No test results" in r for r in exc.value.reasons)


def test_unavailable_transition_lists_what_is_possible(
    session: Session, bg_case: OnboardingCase
) -> None:
    with pytest.raises(workflow.TransitionError) as exc:
        workflow.fire(
            session, bg_case, "support_signoff", actor="x", actor_role=workflow.Role.SUPPORT,
        )
    assert "not available from DRAFT" in exc.value.message
    assert any("submit" in r for r in exc.value.reasons)


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #

def test_human_decisions_are_recorded_as_approvals(
    session: Session, bg_case: OnboardingCase
) -> None:
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    workflow.fire(
        session, bg_case, "support_signoff", actor="syahidah",
        actor_role=workflow.Role.SUPPORT,
        ctx=workflow.GateContext(report=_clean(), package_complete=True),
        comment="verified", rule_set_version="v0.6",
    )
    session.commit()
    approvals = session.query(Approval).filter(Approval.case_id == bg_case.id).all()
    assert len(approvals) == 1
    assert approvals[0].decision == "APPROVED"
    assert approvals[0].actor == "syahidah"
    assert approvals[0].rule_set_version == "v0.6"


def test_rejections_are_recorded_as_rejections(session: Session, bg_case: OnboardingCase) -> None:
    bg_case.state = str(workflow.State.SUPPORT_REVIEW)
    session.commit()
    workflow.fire(
        session, bg_case, "request_changes", actor="jon", actor_role=workflow.Role.SUPPORT,
        comment="SDT clause missing",
    )
    session.commit()
    approval = session.query(Approval).filter(Approval.case_id == bg_case.id).one()
    assert approval.decision == "REJECTED"
    assert bg_case.state == str(workflow.State.RULES_DRAFTED)


def test_system_moves_are_audited_but_not_approvals(
    session: Session, bg_case: OnboardingCase
) -> None:
    bg_case.state = str(workflow.State.REQUIREMENT_APPROVED)
    session.commit()
    workflow.fire(
        session, bg_case, "compile_rules", actor="platform", actor_role=workflow.Role.SYSTEM,
    )
    session.commit()
    assert session.query(Approval).filter(Approval.case_id == bg_case.id).count() == 0
    events = session.query(AuditEvent).filter(AuditEvent.case_id == bg_case.id).all()
    assert any(e.action == "transition:compile_rules" for e in events)


def test_package_pending_round_trip(session: Session, bg_case: OnboardingCase) -> None:
    """The replacement for an email chasing Support."""
    bg_case.state = str(workflow.State.RULES_DRAFTED)
    session.commit()

    workflow.fire(
        session, bg_case, "request_package_update", actor="jon",
        actor_role=workflow.Role.SUPPORT, comment="BG missing from package",
    )
    assert bg_case.state == str(workflow.State.PACKAGE_PENDING)
    approval = session.query(Approval).filter(Approval.case_id == bg_case.id).one()
    assert approval.decision == "REQUESTED"

    workflow.fire(
        session, bg_case, "package_uploaded", actor="jon", actor_role=workflow.Role.SUPPORT,
    )
    assert bg_case.state == str(workflow.State.RULES_DRAFTED)


def test_full_happy_path_to_handover(session: Session, bg_case: OnboardingCase) -> None:
    clean = workflow.GateContext(report=_clean(), package_complete=True)
    passing = workflow.GateContext(
        report=_clean(), package_complete=True, tests_total=14, tests_passed=14, tests_failed=0,
    )
    steps = [
        ("submit", workflow.Role.COUNTRY, None),
        ("approve_requirement", workflow.Role.PM, None),
        ("compile_rules", workflow.Role.SYSTEM, None),
        ("submit_for_support_review", workflow.Role.SYSTEM, clean),
        ("support_signoff", workflow.Role.SUPPORT, clean),
        ("execute_tests", workflow.Role.SYSTEM, None),
        ("record_results", workflow.Role.SYSTEM, None),
        ("submit_for_country_signoff", workflow.Role.SUPPORT, passing),
        ("country_accepts", workflow.Role.COUNTRY, passing),
        ("confirm_production_upload", workflow.Role.SUPPORT, None),
        ("close", workflow.Role.PM, None),
    ]
    for name, role, ctx in steps:
        workflow.fire(session, bg_case, name, actor=f"{role}", actor_role=role, ctx=ctx)
    session.commit()
    assert bg_case.state == str(workflow.State.COMPLETED)
    # Seven human decisions (country×2, PM×2, Support×3); four system moves.
    assert session.query(Approval).filter(Approval.case_id == bg_case.id).count() == 7
    system_moves = [
        e for e in session.query(AuditEvent).filter(AuditEvent.case_id == bg_case.id).all()
        if e.detail.get("role") == "SYSTEM"
    ]
    assert len(system_moves) == 4


def test_gate_reasons_are_reported_without_firing(
    session: Session, bg_case: OnboardingCase
) -> None:
    """The UI asks what is blocking before offering the button."""
    transition = workflow.find_transition(workflow.State.SUPPORT_REVIEW, "support_signoff")
    assert transition is not None
    reasons = workflow.gate_reasons(
        transition, workflow.GateContext(report=_blocked(2), package_complete=False)
    )
    assert len(reasons) == 2
    assert workflow.gate_reasons(
        transition, workflow.GateContext(report=_clean(), package_complete=True)
    ) == []
