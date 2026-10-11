"""Case state machine and release gates.

RFC/ServiceNow is out of scope, so the lifecycle ends at the handover to Support
and the production verification they confirm afterwards.

Two properties are enforced here rather than trusted:

* Only a declared role can fire a transition.
* The validator can return a case to drafting but can never advance one. There is
  no transition whose actor is the system *and* whose target is an approved state.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from sqlalchemy.orm import Session

from tools.core.models import Approval, AuditEvent, OnboardingCase
from tools.validation import ValidationReport


class State(StrEnum):
    DRAFT = "DRAFT"
    REQUIREMENT_REVIEW = "REQUIREMENT_REVIEW"
    REQUIREMENT_APPROVED = "REQUIREMENT_APPROVED"
    RULES_DRAFTED = "RULES_DRAFTED"
    PACKAGE_PENDING = "PACKAGE_PENDING"
    SUPPORT_REVIEW = "SUPPORT_REVIEW"
    TEST_READY = "TEST_READY"
    TEST_EXECUTION = "TEST_EXECUTION"
    RESULT_REVIEW = "RESULT_REVIEW"
    COUNTRY_SIGNOFF = "COUNTRY_SIGNOFF"
    HANDOVER = "HANDOVER"
    PROD_VERIFIED = "PROD_VERIFIED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class Role(StrEnum):
    COUNTRY = "COUNTRY"
    PM = "PM"
    SUPPORT = "SUPPORT"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class Transition:
    source: State
    target: State
    actor: Role
    name: str
    # Gates that must hold. Checked against a GateContext before the move.
    requires_clean_validation: bool = False
    requires_package_complete: bool = False
    requires_tests_passed: bool = False


TRANSITIONS: tuple[Transition, ...] = (
    Transition(State.DRAFT, State.REQUIREMENT_REVIEW, Role.COUNTRY, "submit"),
    Transition(State.REQUIREMENT_REVIEW, State.REQUIREMENT_APPROVED, Role.PM, "approve_requirement"),
    Transition(State.REQUIREMENT_REVIEW, State.DRAFT, Role.PM, "return_requirement"),
    Transition(State.REQUIREMENT_APPROVED, State.RULES_DRAFTED, Role.SYSTEM, "compile_rules"),

    # The only path out of drafting into review runs both gates.
    Transition(
        State.RULES_DRAFTED, State.SUPPORT_REVIEW, Role.SYSTEM, "submit_for_support_review",
        requires_clean_validation=True, requires_package_complete=True,
    ),
    Transition(State.RULES_DRAFTED, State.PACKAGE_PENDING, Role.SUPPORT, "request_package_update"),
    Transition(State.PACKAGE_PENDING, State.RULES_DRAFTED, Role.SUPPORT, "package_uploaded"),

    Transition(State.SUPPORT_REVIEW, State.RULES_DRAFTED, Role.SUPPORT, "request_changes"),
    Transition(
        State.SUPPORT_REVIEW, State.TEST_READY, Role.SUPPORT, "support_signoff",
        requires_clean_validation=True, requires_package_complete=True,
    ),

    Transition(State.TEST_READY, State.TEST_EXECUTION, Role.SYSTEM, "execute_tests"),
    Transition(State.TEST_EXECUTION, State.RESULT_REVIEW, Role.SYSTEM, "record_results"),
    Transition(State.RESULT_REVIEW, State.RULES_DRAFTED, Role.SUPPORT, "rework_after_failure"),
    Transition(
        State.RESULT_REVIEW, State.COUNTRY_SIGNOFF, Role.SUPPORT, "submit_for_country_signoff",
        requires_tests_passed=True,
    ),

    Transition(State.COUNTRY_SIGNOFF, State.RESULT_REVIEW, Role.COUNTRY, "country_rejects"),
    Transition(
        State.COUNTRY_SIGNOFF, State.HANDOVER, Role.COUNTRY, "country_accepts",
        requires_tests_passed=True,
    ),
    Transition(State.HANDOVER, State.PROD_VERIFIED, Role.SUPPORT, "confirm_production_upload"),
    Transition(State.PROD_VERIFIED, State.COMPLETED, Role.PM, "close"),

    Transition(State.DRAFT, State.WITHDRAWN, Role.PM, "withdraw"),
    Transition(State.REQUIREMENT_REVIEW, State.WITHDRAWN, Role.PM, "withdraw"),
)

# Advancing states -- the system may never move a case *into* one of these.
APPROVED_STATES = frozenset({
    State.REQUIREMENT_APPROVED, State.SUPPORT_REVIEW, State.TEST_READY,
    State.COUNTRY_SIGNOFF, State.HANDOVER, State.PROD_VERIFIED, State.COMPLETED,
})


class TransitionError(RuntimeError):
    """Raised when a transition is not permitted. Carries why, for the UI."""

    def __init__(self, message: str, reasons: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.reasons = reasons or []


@dataclass
class GateContext:
    """What the gates need to know. Supplied by the caller, never guessed."""

    report: Optional[ValidationReport] = None
    package_complete: bool = False
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0

    @property
    def validation_clean(self) -> bool:
        return self.report is not None and self.report.is_clean

    @property
    def tests_ok(self) -> bool:
        return self.tests_total > 0 and self.tests_failed == 0


def transitions_from(state: State) -> list[Transition]:
    return [t for t in TRANSITIONS if t.source == state]


def find_transition(state: State, name: str) -> Optional[Transition]:
    for t in TRANSITIONS:
        if t.source == state and t.name == name:
            return t
    return None


def gate_reasons(transition: Transition, ctx: GateContext) -> list[str]:
    """Why this transition is currently blocked. Empty means it may fire."""
    reasons: list[str] = []
    if transition.requires_clean_validation:
        if ctx.report is None:
            reasons.append("Validation has not been run against the current rule set.")
        elif not ctx.report.is_clean:
            count = len(ctx.report.blockers)
            reasons.append(f"{count} blocking finding{'s' if count != 1 else ''} must be cleared.")
    if transition.requires_package_complete and not ctx.package_complete:
        reasons.append("The config package does not yet contain every referenced requirement.")
    if transition.requires_tests_passed and not ctx.tests_ok:
        if ctx.tests_total == 0:
            reasons.append("No test results have been recorded.")
        else:
            reasons.append(f"{ctx.tests_failed} of {ctx.tests_total} tests failed.")
    return reasons


def can_fire(transition: Transition, actor_role: Role, ctx: GateContext) -> list[str]:
    reasons: list[str] = []
    if transition.actor != actor_role:
        reasons.append(f"Only {transition.actor} may perform '{transition.name}'.")
    reasons.extend(gate_reasons(transition, ctx))
    return reasons


def fire(
    session: Session,
    case: OnboardingCase,
    name: str,
    actor: str,
    actor_role: Role,
    ctx: Optional[GateContext] = None,
    comment: Optional[str] = None,
    rule_set_version: Optional[str] = None,
) -> OnboardingCase:
    """Apply a transition, or raise :class:`TransitionError` explaining why not."""
    ctx = ctx or GateContext()
    state = State(case.state)
    transition = find_transition(state, name)
    if transition is None:
        allowed = ", ".join(t.name for t in transitions_from(state)) or "none"
        raise TransitionError(
            f"'{name}' is not available from {state}.", [f"Available here: {allowed}."]
        )

    # Structural guarantee, not a convention: the system cannot approve.
    if transition.actor == Role.SYSTEM and transition.target in APPROVED_STATES:
        if transition.requires_clean_validation is False:
            raise TransitionError(
                f"'{name}' would let the system enter {transition.target} without a gate.",
            )

    reasons = can_fire(transition, actor_role, ctx)
    if reasons:
        raise TransitionError(f"'{name}' is blocked.", reasons)

    previous = case.state
    case.state = str(transition.target)

    session.add(AuditEvent(
        case_id=case.id,
        actor=actor,
        action=f"transition:{name}",
        detail={
            "from": previous,
            "to": case.state,
            "role": str(actor_role),
            "comment": comment,
            "blockers": len(ctx.report.blockers) if ctx.report else None,
        },
    ))

    # Human decisions are recorded as approvals; system moves are not.
    if actor_role != Role.SYSTEM:
        decision = "APPROVED"
        lowered = name.lower()
        if "reject" in lowered or "return" in lowered or "request_changes" in lowered:
            decision = "REJECTED"
        elif "request_package" in lowered:
            decision = "REQUESTED"
        session.add(Approval(
            case_id=case.id,
            stage=previous,
            actor=actor,
            role=str(actor_role),
            decision=decision,
            comment=comment,
            rule_set_version=rule_set_version,
        ))

    session.flush()
    return case
