"""Timeline planning — PM questionnaire, baseline estimate and plan validation.

The AI ``timeline_planner`` proposes the plan; this package supplies the fixed
milestone sequence, the structured questions asked of the PM, a deterministic
baseline estimate the planner starts from, and the checks every plan must pass.
"""
from .planning import (
    MILESTONES,
    QUESTIONS,
    add_working_days,
    complexity_facts,
    estimate,
    gate_plan,
    normalise_answers,
    validate_plan,
)

__all__ = [
    "MILESTONES", "QUESTIONS", "add_working_days", "complexity_facts", "estimate",
    "gate_plan", "normalise_answers", "validate_plan",
]
