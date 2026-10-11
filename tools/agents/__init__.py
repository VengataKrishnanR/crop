"""Agent factories for the CCRE advisory layer.

Eight narrow agents, each with one job, a typed output contract
(:mod:`tools.agents.schemas`) and the smallest tool set that job needs. There is
deliberately no "do everything" agent, and no agent holds workflow state — the
state machine does.

The builder modules import google-adk, so they are imported lazily here: the
schemas and :data:`AGENT_SPECS` stay importable (and the platform still ingests,
validates and gates) without ADK or a model credential.
"""
from __future__ import annotations

from typing import Any, Optional

from .schemas import (
    BusinessRequirement,
    ChangeSet,
    Condition,
    FailureAnalysis,
    GeneratedPayload,
    IntakeTurn,
    ProposedRule,
    RequirementInterpretation,
    ResponseReview,
    TestCase,
    TestCaseSuite,
    TimelinePlan,
)

__all__ = [
    "ChangeSet", "Condition", "FailureAnalysis", "ProposedRule",
    "RequirementInterpretation", "TestCase", "TestCaseSuite", "BusinessRequirement",
    "IntakeTurn", "TimelinePlan", "GeneratedPayload", "ResponseReview",
    "AGENT_SPECS", "agents_available",
    "build_intake_assistant_agent", "build_requirement_interpreter_agent",
    "build_timeline_planner_agent", "build_rule_drafter_agent",
    "build_test_case_designer_agent", "build_payload_generator_agent",
    "build_response_reviewer_agent", "build_failure_analyst_agent",
]

AGENT_SPECS: dict[str, dict[str, Any]] = {
    "intake_assistant": {
        "stage": "Requirement intake",
        "purpose": "Interview the business team (chat) until the requirement is complete.",
        "output": "IntakeTurn → BusinessRequirement",
        "gate": "CCRE consultant approves the requirement.",
    },
    "requirement_interpreter": {
        "stage": "Requirement intake",
        "purpose": "Turn a form + free-text requirement into a structured reading (NLP).",
        "output": "RequirementInterpretation",
        "gate": "CCRE consultant approves the requirement.",
    },
    "timeline_planner": {
        "stage": "Timeline",
        "purpose": "Plan the seven delivery milestones from the PM questionnaire.",
        "output": "TimelinePlan",
        "gate": "PM approves; the approved plan is published to the business team.",
    },
    "rule_drafter": {
        "stage": "Rule config + DMG",
        "purpose": "Convert the approved business requirement into M2C rule rows.",
        "output": "ChangeSet (staged, never applied)",
        "gate": "A named CCRE user accepts it; the validator then runs.",
    },
    "test_case_designer": {
        "stage": "UAT test case prep",
        "purpose": "Draft the UAT suite from the M2C draft, with business-readable summaries.",
        "output": "TestCaseSuite",
        "gate": "CCRE team reviews, then the business team.",
    },
    "payload_generator": {
        "stage": "UAT execution",
        "purpose": "Adapt the sample payload to each approved test case.",
        "output": "GeneratedPayload",
        "gate": "Every change is recorded with the result.",
    },
    "response_reviewer": {
        "stage": "UAT execution",
        "purpose": "Review each endpoint response against the expectation and explain it.",
        "output": "ResponseReview",
        "gate": "Deterministic check is authoritative when conclusive; CCRE team reviews results.",
    },
    "failure_analyst": {
        "stage": "UAT review",
        "purpose": "Explain a failed UAT result and recommend the next check.",
        "output": "FailureAnalysis",
        "gate": "Recommendation only; the CCRE team decides whether to correct the M2C.",
    },
}

_BUILDERS = {
    "build_intake_assistant_agent": "intake_assistant",
    "build_timeline_planner_agent": "timeline_planner",
    "build_payload_generator_agent": "payload_generator",
    "build_response_reviewer_agent": "response_reviewer",
    "build_requirement_interpreter_agent": "requirement_interpreter",
    "build_rule_drafter_agent": "rule_drafter",
    "build_test_case_designer_agent": "test_case_designer",
    "build_failure_analyst_agent": "failure_analyst",
}


def __getattr__(name: str) -> Any:
    """Import a builder module on first use so ADK is only needed when agents are built."""
    module = _BUILDERS.get(name)
    if module is None:
        raise AttributeError(name)
    from importlib import import_module

    return getattr(import_module(f".{module}", __name__), name)


def agents_available() -> tuple[bool, Optional[str]]:
    """Whether the advisory layer can start, and why not if it cannot."""
    from tools.core.config import SETTINGS

    if not SETTINGS.agents_enabled:
        return False, "Advisory layer disabled by CCRE_AGENTS_ENABLED."
    try:
        import google.adk  # noqa: F401
    except ImportError as exc:
        return False, f"google-adk not installed: {exc}"
    return True, None
