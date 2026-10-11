"""Response reviewer agent — judges one UAT endpoint response.

The deterministic checker decides whenever it can read the response; the
reviewer then explains the verdict. Only when the response shape is not
recognised does the reviewer's own verdict stand (and it is marked as AI).
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from ._prompt import load_prompt

NAME = "response_reviewer"


def build_response_reviewer_agent(model):
    """Build the response reviewer. Works only from what it is given — no tools."""
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Reviews a CCRE endpoint response for one UAT test case against the expectation "
            "and explains the verdict in technical and business terms."
        ),
        instruction=load_prompt("response_reviewer_agent"),
        tools=[],
    )
