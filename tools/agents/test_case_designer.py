"""Test case designer agent — covering suite for a validated rule set.

Stage 3 of the advisory flow. Emits a TestCaseSuite; a reviewer approves it and
approved cases become test evidence.
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from tools.functions import check_expression, find_similar_rules, get_requirement_definition

from ._prompt import load_prompt

NAME = "test_case_designer"


def build_test_case_designer_agent(model):
    """Build the test case designer.

    Args:
        model: Shared LLM instance.

    Returns:
        Configured Agent. Read-only tools only.
    """
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Designs positive, negative, boundary, missing-data and regression test cases "
            "for a CCRE rule set. Produces a TestCaseSuite and names any condition it "
            "could not cover."
        ),
        instruction=load_prompt("test_case_designer_agent", expression_notes=True),
        tools=[
            FunctionTool(find_similar_rules),
            FunctionTool(get_requirement_definition),
            FunctionTool(check_expression),
        ],
    )
