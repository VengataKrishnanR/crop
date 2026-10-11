"""Onboarding-case workflow.

The state machine lives in :mod:`tools.workflow.state_machine`. Control flow is
enforced in code, not in a prompt: agents decide content, this decides sequence,
and no agent can fire a transition.
"""
from .state_machine import (
    APPROVED_STATES,
    TRANSITIONS,
    GateContext,
    Role,
    State,
    Transition,
    TransitionError,
    can_fire,
    find_transition,
    fire,
    gate_reasons,
    transitions_from,
)

__all__ = [
    "APPROVED_STATES", "TRANSITIONS", "GateContext", "Role", "State", "Transition",
    "TransitionError", "can_fire", "find_transition", "fire", "gate_reasons", "transitions_from",
]
