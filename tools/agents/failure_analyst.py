"""Failure analyst agent — root cause for one failed test execution.

Stage 4 of the advisory flow. Emits a FailureAnalysis that recommends the next
check. It never edits; a human decides whether anything changes.
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from tools.functions import (
    check_expression,
    country_package_status,
    find_similar_rules,
    get_requirement_definition,
)

from ._prompt import load_prompt

NAME = "failure_analyst"


def build_failure_analyst_agent(model):
    """Build the failure analyst.

    Args:
        model: Shared LLM instance.

    Returns:
        Configured Agent. Read-only tools only.
    """
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Diagnoses a failed CCRE test execution, checking payload, config package and "
            "expected result before the rule logic, and recommends the next check."
        ),
        instruction=load_prompt("failure_analyst_agent", expression_notes=True),
        tools=[
            FunctionTool(get_requirement_definition),
            FunctionTool(country_package_status),
            FunctionTool(check_expression),
            FunctionTool(find_similar_rules),
        ],
    )
