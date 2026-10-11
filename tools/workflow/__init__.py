"""Onboarding-case workflow.

The state machine lives in :mod:`tools.workflow.state_machine`; the case
helpers (M2C draft, gate facts) in :mod:`tools.workflow.case_facts`. Control
flow is enforced in code, not in a prompt: agents decide content, this decides
sequence, and no agent can fire a transition.
"""
from .state_machine import (
    APPROVED_STATES,
    STAGES,
    STATE_LABELS,
    TERMINAL_STATES,
    TRANSITIONS,
    GateContext,
    Role,
    Stage,
    State,
    Transition,
    TransitionError,
    can_fire,
    find_transition,
    fire,
    gate_reasons,
    stage_of,
    transitions_from,
)

__all__ = [
    "APPROVED_STATES", "STAGES", "STATE_LABELS", "TERMINAL_STATES", "TRANSITIONS",
    "GateContext", "Role", "Stage", "State", "Transition", "TransitionError",
    "can_fire", "find_transition", "fire", "gate_reasons", "stage_of", "transitions_from",
]
