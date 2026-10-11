"""Requirement interpreter agent — natural-language requirement to structured reading.

Stage 1 of the advisory flow. Emits a RequirementInterpretation, which a PM
approves before any rule is drafted.
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from tools.functions import country_package_status, list_requirement_groups

from ._prompt import load_prompt

NAME = "requirement_interpreter"


def build_requirement_interpreter_agent(model):
    """Build the requirement interpreter.

    Args:
        model: Shared LLM instance (see ``components.llm.build_model_for_env``).

    Returns:
        Configured Agent. Read-only tools only.
    """
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Reads a country onboarding requirement (often an email) and returns a structured "
            "RequirementInterpretation: country, shipment type, requirement groups, conditions, "
            "and every ambiguity it could not resolve."
        ),
        instruction=load_prompt("requirement_interpreter_agent"),
        tools=[
            FunctionTool(list_requirement_groups),
            FunctionTool(country_package_status),
        ],
    )
