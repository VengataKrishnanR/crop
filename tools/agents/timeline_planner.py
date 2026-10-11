"""Timeline planner agent — dated plan from the PM questionnaire.

Starts from the deterministic baseline in :mod:`tools.timeline`; every plan it
returns is checked by :func:`tools.timeline.validate_plan` before it is stored.
"""
from __future__ import annotations

from google.adk.agents.llm_agent import Agent

from ._prompt import load_prompt

NAME = "timeline_planner"


def build_timeline_planner_agent(model):
    """Build the timeline planner. Works only from the facts it is given — no tools."""
    return Agent(
        model=model,
        name=NAME,
        description=(
            "Turns the PM questionnaire answers and the onboarding complexity facts into a "
            "seven-milestone dated plan (rule config + DMG through RTP) with assumptions and risks."
        ),
        instruction=load_prompt("timeline_planner_agent"),
        tools=[],
    )
