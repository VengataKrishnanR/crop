"""Rule drafter agent — candidate rule rows for an approved requirement.

Stage 2 of the advisory flow. Emits a ChangeSet. The agent holds read-only tools
only: the server validates the ChangeSet and stages it with
:func:`tools.functions.stage_change_set`, so no model output reaches the rule
tables without a human accepting it.
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from tools.functions import (
    check_expression,
    country_package_status,
    find_similar_rules,
    get_requirement_definition,
    list_requirement_groups,
)

from ._prompt import load_prompt

NAME = "rule_drafter"


def build_rule_drafter_agent(model):
    """Build the rule drafter.

    Args:
        model: Shared LLM instance.

    Returns:
        Configured Agent with catalogue lookups and the expression checker.
    """
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Drafts candidate CCRE rule rows and condition expressions for an approved "
            "requirement, reusing existing rule shapes. Produces a ChangeSet proposal that "
            "is staged and validated, never applied directly."
        ),
        instruction=load_prompt("rule_drafter_agent", expression_notes=True),
        tools=[
            FunctionTool(find_similar_rules),
            FunctionTool(country_package_status),
            FunctionTool(get_requirement_definition),
            FunctionTool(list_requirement_groups),
            FunctionTool(check_expression),
        ],
    )
