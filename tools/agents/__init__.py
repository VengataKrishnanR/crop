"""Agent factories for the CCRE advisory layer.

Four narrow agents, each with one job, a typed output contract
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
    ChangeSet,
    Condition,
    FailureAnalysis,
    ProposedRule,
    RequirementInterpretation,
    TestCase,
    TestCaseSuite,
)

__all__ = [
    "ChangeSet", "Condition", "FailureAnalysis", "ProposedRule",
    "RequirementInterpretation", "TestCase", "TestCaseSuite",
    "AGENT_SPECS", "agents_available",
    "build_requirement_interpreter_agent", "build_rule_drafter_agent",
    "build_test_case_designer_agent", "build_failure_analyst_agent",
]

AGENT_SPECS: dict[str, dict[str, Any]] = {
    "requirement_interpreter": {
        "purpose": "Turn a natural-language country requirement into a structured reading.",
        "output": "RequirementInterpretation",
        "gate": "PM approves the interpretation before rules are drafted.",
    },
    "rule_drafter": {
        "purpose": "Propose candidate rule rows for an approved requirement, reusing what exists.",
        "output": "ChangeSet (staged, never applied)",
        "gate": "Validator must pass, then Support signs off.",
    },
    "test_case_designer": {
        "purpose": "Draft a covering test suite for a validated rule set.",
        "output": "TestCaseSuite",
        "gate": "Reviewer approves the suite; approved cases become evidence.",
    },
    "failure_analyst": {
        "purpose": "Explain a failed execution and recommend the next check.",
        "output": "FailureAnalysis",
        "gate": "Recommendation only; a human decides whether to change anything.",
    },
}

_BUILDERS = {
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
