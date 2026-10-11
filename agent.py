"""ADK entry point — CCRE Rules Intelligence & Onboarding agent.

The root agent orchestrates via two layers of tools:
  - 4 AgentTools: specialist sub-agents (interpret → draft → test design → failure analysis)
  - Read-only FunctionTools: catalogue lookups, expression checking, deterministic
    validation, and rule-set discovery

Eight agents are built in total (``SUB_AGENTS``); the server invokes each one at
its lifecycle step (intake chat, timeline, M2C draft, UAT prep/execution/review).

No tool can approve, transition a case, seal a rule set, or reach CCRE. Staging a
drafted ChangeSet is done by the server after validation, never by an agent.

Run with ``adk web .`` from this folder, or through the FastAPI server
(``uvicorn server.app:app``), whose UI chat calls this ``root_agent``.
"""
from __future__ import annotations

from pathlib import Path

from google.adk.agents.llm_agent import Agent
from google.adk.tools import AgentTool, FunctionTool

from components.llm import build_model_for_env
from components.logging import configure_logging
from components.tracing import apply_tracing_patch
from tools.agents import (
    build_failure_analyst_agent,
    build_intake_assistant_agent,
    build_payload_generator_agent,
    build_requirement_interpreter_agent,
    build_response_reviewer_agent,
    build_rule_drafter_agent,
    build_test_case_designer_agent,
    build_timeline_planner_agent,
)
from tools.core.db import init_db
from tools.functions import (
    check_expression,
    country_package_status,
    find_similar_rules,
    get_requirement_definition,
    list_requirement_groups,
    list_rule_sets,
    validate_rule_set,
)

configure_logging()
apply_tracing_patch()
init_db()  # tools query the database; make sure the schema exists under adk web too

_PROMPT = Path(__file__).parent / "prompts" / "root_agent.md"

# Model — selected by CCRE_LLM_MODE env var (stub | openai | google-ai | apigee).
model = build_model_for_env()

# ---------------------------------------------------------------------------
# Sub-agents
# ---------------------------------------------------------------------------

# Lifecycle order: intake → timeline → M2C → UAT prep → UAT execution → UAT review.
intake_assistant = build_intake_assistant_agent(model)
requirement_interpreter = build_requirement_interpreter_agent(model)
timeline_planner = build_timeline_planner_agent(model)
rule_drafter = build_rule_drafter_agent(model)
test_case_designer = build_test_case_designer_agent(model)
payload_generator = build_payload_generator_agent(model)
response_reviewer = build_response_reviewer_agent(model)
failure_analyst = build_failure_analyst_agent(model)

# Every agent the server can invoke for a lifecycle step.
SUB_AGENTS = {
    "intake_assistant": intake_assistant,
    "requirement_interpreter": requirement_interpreter,
    "timeline_planner": timeline_planner,
    "rule_drafter": rule_drafter,
    "test_case_designer": test_case_designer,
    "payload_generator": payload_generator,
    "response_reviewer": response_reviewer,
    "failure_analyst": failure_analyst,
}

# The subset the internal "Ask Expert" orchestrator may delegate to.
ROOT_DELEGATES = ("requirement_interpreter", "rule_drafter", "test_case_designer", "failure_analyst")

# ---------------------------------------------------------------------------
# Root orchestrator
# ---------------------------------------------------------------------------

root_agent = Agent(
    model=model,
    name="ccre_orchestrator",
    description=(
        "CCRE onboarding assistant — interprets country requirements, drafts candidate "
        "rules, designs test suites and analyses failures, using read-only catalogue "
        "and validation tools. Recommends only; humans approve."
    ),
    instruction=_PROMPT.read_text(encoding="utf-8").replace("{", "｛").replace("}", "｝"),
    tools=[
        # ── Specialist sub-agents ────────────────────────────────────────────
        *(AgentTool(SUB_AGENTS[name]) for name in ROOT_DELEGATES),

        # ── Read-only catalogue and validation tools ─────────────────────────
        FunctionTool(list_requirement_groups),
        FunctionTool(find_similar_rules),
        FunctionTool(get_requirement_definition),
        FunctionTool(check_expression),
        FunctionTool(country_package_status),
        FunctionTool(validate_rule_set),
        FunctionTool(list_rule_sets),
    ],
)
