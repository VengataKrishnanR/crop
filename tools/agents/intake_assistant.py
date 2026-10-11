"""Intake assistant agent — the requirement chatbot for business teams.

Interviews the user one question at a time until the requirement is complete,
then emits the structured BusinessRequirement for confirmation.
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from tools.functions import country_package_status, list_requirement_groups

from ._prompt import load_prompt

NAME = "intake_assistant"


def build_intake_assistant_agent(model):
    """Build the intake chatbot. Read-only catalogue tools only."""
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Interviews a country business team about a new customs requirement, one question "
            "at a time, and produces a structured BusinessRequirement once complete."
        ),
        instruction=load_prompt("intake_assistant_agent"),
        tools=[FunctionTool(list_requirement_groups), FunctionTool(country_package_status)],
    )
