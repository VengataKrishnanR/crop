"""Payload generator agent — adapts the sample payload to one UAT test case."""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent
from google.adk.tools import FunctionTool

from tools.functions import get_requirement_definition

from ._prompt import load_prompt

NAME = "payload_generator"


def build_payload_generator_agent(model):
    """Build the payload generator. May look up requirement attributes; nothing else."""
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Adapts a sample CCRE request payload so it exercises exactly one UAT test case, "
            "recording every change and assumption."
        ),
        instruction=load_prompt("payload_generator_agent", expression_notes=True),
        tools=[FunctionTool(get_requirement_definition)],
    )
