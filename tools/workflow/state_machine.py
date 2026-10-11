"""Country-onboarding lifecycle — states, roles, transitions and release gates.

The lifecycle follows the CCRE onboarding sequence:

    Intake → requirement review (CCRE consultant) → timeline (AI from PM answers,
    PM approves, published to business) → rule config + DMG changes (M2C draft)
    → sanity check → UAT test case prep → UAT test case review (CCRE team, then
    business) → UAT execution → UAT result review (CCRE team; failures loop back
    to rule config) → business UAT sign-off → RTP → completed.

Two properties are enforced here rather than trusted:

* Only a declared role can fire a transition.
* A gate (clean validation, complete package, approved test cases, passing
  results, …) is evaluated from facts the caller computes; nobody can waive it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from sqlalchemy.orm import Session

from tools.core.models import Approval, AuditEvent, OnboardingCase
from tools.validation import ValidationReport


class State(StrEnum):
    INTAKE = "INTAKE"
    REQUIREMENT_REVIEW = "REQUIREMENT_REVIEW"
    TIMELINE_PLANNING = "TIMELINE_PLANNING"
    TIMELINE_REVIEW = "TIMELINE_REVIEW"
    RULE_CONFIG = "RULE_CONFIG"
    SANITY_CHECK = "SANITY_CHECK"
    UAT_TC_PREP = "UAT_TC_PREP"
    UAT_TC_REVIEW_CCRE = "UAT_TC_REVIEW_CCRE"
    UAT_TC_REVIEW_BUSINESS = "UAT_TC_REVIEW_BUSINESS"
    UAT_EXECUTION = "UAT_EXECUTION"
    UAT_RESULT_REVIEW = "UAT_RESULT_REVIEW"
    UAT_SIGNOFF = "UAT_SIGNOFF"
    RTP = "RTP"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class Role(StrEnum):
    ADMIN = "ADMIN"
    PM = "PM"
    CCRE_CONSULTANT = "CCRE_CONSULTANT"
    CCRE_TEAM = "CCRE_TEAM"
    BUSINESS = "BUSINESS"
    SYSTEM = "SYSTEM"


_CCRE = frozenset({Role.CCRE_TEAM, Role.CCRE_CONSULTANT})


@dataclass(frozen=True)
class Transition:
    source: State
    target: State
    actors: frozenset[Role]
    name: str
    label: str
    # Gates that must hold. Checked against a GateContext before the move.
    requires_requirement: bool = False
    requires_timeline: bool = False
    requires_rule_set: bool = False
    requires_clean_validation: bool = False
    requires_package_complete: bool = False
    requires_test_cases: bool = False
    requires_execution_complete: bool = False
    requires_tests_passed: bool = False

    @property
    def actor_names(self) -> list[str]:
        return sorted(str(a) for a in self.actors)


def _t(source: State, target: State, actors, name: str, label: str, **gates) -> Transition:
    return Transition(source, target, frozenset(actors), name, label, **gates)


TRANSITIONS: tuple[Transition, ...] = (
    # ── 1. Intake and requirement approval (CCRE consultant) ────────────────
    _t(State.INTAKE, State.REQUIREMENT_REVIEW, {Role.BUSINESS, Role.CCRE_TEAM, Role.CCRE_CONSULTANT},
       "submit_requirement", "Submit requirement for review", requires_requirement=True),
    _t(State.REQUIREMENT_REVIEW, State.TIMELINE_PLANNING, {Role.CCRE_CONSULTANT},
       "approve_requirement", "Approve requirement", requires_requirement=True),
    _t(State.REQUIREMENT_REVIEW, State.INTAKE, {Role.CCRE_CONSULTANT},
       "return_requirement", "Return requirement for changes"),

    # ── 2. Timeline: AI from PM answers → PM approves → published ───────────
    _t(State.TIMELINE_PLANNING, State.TIMELINE_REVIEW, {Role.PM, Role.CCRE_TEAM},
       "submit_timeline", "Submit timeline for PM approval", requires_timeline=True),
    _t(State.TIMELINE_REVIEW, State.RULE_CONFIG, {Role.PM},
       "approve_timeline", "Approve and publish timeline", requires_timeline=True),
    _t(State.TIMELINE_REVIEW, State.TIMELINE_PLANNING, {Role.PM},
       "return_timeline", "Return timeline for changes"),

    # ── 3. Rule config + DMG changes (M2C draft) → sanity check ─────────────
    _t(State.RULE_CONFIG, State.SANITY_CHECK, {Role.CCRE_TEAM},
       "request_sanity_check", "Send M2C draft to sanity check", requires_rule_set=True),
    _t(State.SANITY_CHECK, State.UAT_TC_PREP, _CCRE,
       "sanity_passed", "Sanity check passed",
       requires_rule_set=True, requires_clean_validation=True, requires_package_complete=True),
    _t(State.SANITY_CHECK, State.RULE_CONFIG, _CCRE,
       "sanity_failed", "Sanity check failed — back to rule config"),

    # ── 4. UAT test case preparation and review (CCRE team, then business) ──
    _t(State.UAT_TC_PREP, State.UAT_TC_REVIEW_CCRE, {Role.CCRE_TEAM},
       "submit_test_cases", "Submit test cases for CCRE review", requires_test_cases=True),
    _t(State.UAT_TC_REVIEW_CCRE, State.UAT_TC_REVIEW_BUSINESS, _CCRE,
       "ccre_approve_test_cases", "CCRE approves test cases", requires_test_cases=True),
    _t(State.UAT_TC_REVIEW_CCRE, State.UAT_TC_PREP, _CCRE,
       "ccre_return_test_cases", "CCRE returns test cases"),
    _t(State.UAT_TC_REVIEW_BUSINESS, State.UAT_EXECUTION, {Role.BUSINESS},
       "business_approve_test_cases", "Business approves test cases", requires_test_cases=True),
    _t(State.UAT_TC_REVIEW_BUSINESS, State.UAT_TC_PREP, {Role.BUSINESS},
       "business_return_test_cases", "Business returns test cases"),

    # ── 5. UAT execution → CCRE result review (with correction loop) ────────
    _t(State.UAT_EXECUTION, State.UAT_RESULT_REVIEW, {Role.CCRE_TEAM, Role.SYSTEM},
       "complete_execution", "Execution complete — to CCRE review", requires_execution_complete=True),
    _t(State.UAT_RESULT_REVIEW, State.RULE_CONFIG, _CCRE,
       "request_correction", "Failures found — correct the M2C and restart the cycle"),
    _t(State.UAT_RESULT_REVIEW, State.UAT_SIGNOFF, _CCRE,
       "ccre_accept_results", "CCRE accepts results — to business sign-off",
       requires_execution_complete=True, requires_tests_passed=True),

    # ── 6. Business sign-off → RTP → completed ───────────────────────────────
    _t(State.UAT_SIGNOFF, State.RTP, {Role.BUSINESS},
       "business_signoff", "Business signs off UAT", requires_tests_passed=True),
    _t(State.UAT_SIGNOFF, State.UAT_RESULT_REVIEW, {Role.BUSINESS},
       "business_reject_results", "Business rejects results"),
    _t(State.RTP, State.COMPLETED, {Role.CCRE_TEAM},
       "confirm_production", "Confirm production upload (RTP done)"),

    # ── withdrawal before configuration starts ───────────────────────────────
    _t(State.INTAKE, State.WITHDRAWN, {Role.PM, Role.CCRE_CONSULTANT}, "withdraw", "Withdraw onboarding"),
    _t(State.REQUIREMENT_REVIEW, State.WITHDRAWN, {Role.PM, Role.CCRE_CONSULTANT}, "withdraw", "Withdraw onboarding"),
    _t(State.TIMELINE_PLANNING, State.WITHDRAWN, {Role.PM}, "withdraw", "Withdraw onboarding"),
)

# States a human approval moves a case into. The system may never move a case
# into one of these.
APPROVED_STATES = frozenset({
    State.TIMELINE_PLANNING, State.RULE_CONFIG, State.UAT_TC_PREP, State.UAT_TC_REVIEW_BUSINESS,
    State.UAT_EXECUTION, State.UAT_SIGNOFF, State.RTP, State.COMPLETED,
})

TERMINAL_STATES = frozenset({State.COMPLETED, State.WITHDRAWN})


# --------------------------------------------------------------------------- #
# Stages — how the states group for display, and what business users see
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    business_label: str
    states: tuple[State, ...]


STAGES: tuple[Stage, ...] = (
    Stage("intake", "Requirement intake", "Requirement", (State.INTAKE, State.REQUIREMENT_REVIEW)),
    Stage("timeline", "Timeline", "Timeline", (State.TIMELINE_PLANNING, State.TIMELINE_REVIEW)),
    Stage("rule_config", "Rule config + DMG", "Configuration", (State.RULE_CONFIG,)),
    Stage("sanity", "Sanity check", "Configuration", (State.SANITY_CHECK,)),
    Stage("uat_prep", "UAT test case prep", "Test preparation", (State.UAT_TC_PREP,)),
    Stage("uat_review", "UAT test case review", "Test case review",
          (State.UAT_TC_REVIEW_CCRE, State.UAT_TC_REVIEW_BUSINESS)),
    Stage("uat_execution", "UAT execution", "Testing", (State.UAT_EXECUTION,)),
    Stage("uat_signoff", "UAT review + sign-off", "Sign-off", (State.UAT_RESULT_REVIEW, State.UAT_SIGNOFF)),
    Stage("rtp", "RTP", "Go-live", (State.RTP, State.COMPLETED)),
)

STATE_LABELS: dict[State, str] = {
    State.INTAKE: "Capturing requirement",
    State.REQUIREMENT_REVIEW: "Requirement with CCRE consultant",
    State.TIMELINE_PLANNING: "Timeline being planned",
    State.TIMELINE_REVIEW: "Timeline with PM for approval",
    State.RULE_CONFIG: "Rule configuration + DMG changes",
    State.SANITY_CHECK: "Sanity check",
    State.UAT_TC_PREP: "Preparing UAT test cases",
    State.UAT_TC_REVIEW_CCRE: "Test cases with CCRE team",
    State.UAT_TC_REVIEW_BUSINESS: "Test cases with business team",
    State.UAT_EXECUTION: "UAT execution",
    State.UAT_RESULT_REVIEW: "Results with CCRE team",
    State.UAT_SIGNOFF: "Awaiting business sign-off",
    State.RTP: "Ready to production",
    State.COMPLETED: "Live in production",
    State.WITHDRAWN: "Withdrawn",
}


def stage_of(state: State) -> Optional[Stage]:
    for stage in STAGES:
        if state in stage.states:
            return stage
    return None


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #

class TransitionError(RuntimeError):
    """Raised when a transition is not permitted. Carries why, for the UI."""

    def __init__(self, message: str, reasons: Optional[list[str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.reasons = reasons or []


@dataclass
class GateContext:
    """What the gates need to know. Computed by the caller from the database."""

    report: Optional[ValidationReport] = None
    package_complete: bool = False
    has_requirement: bool = False
    has_timeline: bool = False
    has_rule_set: bool = False
    test_cases_ready: int = 0
    execution_complete: bool = False
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
    if transition.requires_requirement and not ctx.has_requirement:
        reasons.append("No requirement has been captured yet (chat or form).")
    if transition.requires_timeline and not ctx.has_timeline:
        reasons.append("No timeline has been generated yet.")
    if transition.requires_rule_set and not ctx.has_rule_set:
        reasons.append("The M2C draft has not been started for this case.")
    if transition.requires_clean_validation:
        if ctx.report is None:
            reasons.append("Validation has not been run against the M2C draft.")
        elif not ctx.report.is_clean:
            count = len(ctx.report.blockers)
            reasons.append(f"{count} blocking finding{'s' if count != 1 else ''} must be cleared.")
    if transition.requires_package_complete and not ctx.package_complete:
        reasons.append("The config package does not yet contain every referenced requirement.")
    if transition.requires_test_cases and ctx.test_cases_ready == 0:
        reasons.append("There are no UAT test cases to review.")
    if transition.requires_execution_complete and not ctx.execution_complete:
        reasons.append("Not every approved test case has an execution result yet.")
    if transition.requires_tests_passed and not ctx.tests_ok:
        if ctx.tests_total == 0:
            reasons.append("No test results have been recorded.")
        else:
            reasons.append(f"{ctx.tests_failed} of {ctx.tests_total} tests did not pass.")
    return reasons


def can_fire(transition: Transition, actor_role: Role, ctx: GateContext) -> list[str]:
    reasons: list[str] = []
    if actor_role not in transition.actors:
        reasons.append(f"Only {', '.join(transition.actor_names)} may perform '{transition.label}'.")
    reasons.extend(gate_reasons(transition, ctx))
    return reasons


def _decision(name: str) -> str:
    lowered = name.lower()
    if any(word in lowered for word in ("return", "reject", "failed", "correction", "withdraw")):
        return "REJECTED"
    if any(word in lowered for word in ("approve", "accept", "signoff", "passed", "confirm")):
        return "APPROVED"
    return "SUBMITTED"


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
    if actor_role == Role.SYSTEM and transition.target in APPROVED_STATES:
        raise TransitionError(f"The system may not move a case into {transition.target}.")

    reasons = can_fire(transition, actor_role, ctx)
    if reasons:
        raise TransitionError(f"'{transition.label}' is blocked.", reasons)

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
        session.add(Approval(
            case_id=case.id,
            stage=previous,
            actor=actor,
            role=str(actor_role),
            decision=_decision(name),
            comment=comment,
            rule_set_version=rule_set_version,
        ))

    session.flush()
    return case
