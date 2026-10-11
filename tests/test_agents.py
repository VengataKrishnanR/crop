"""Advisory layer tests.

What is asserted is the *boundary*: what the tools can and cannot do, that agent
output is validated against typed schemas, and that a proposal is inert until a
human accepts it. Agents are run for real through ADK with the stub LLM, so the
wiring (prompts, tools, AgentTools, invoker, validators) is exercised end to end
without a network call.
"""
from __future__ import annotations

import inspect
import json

import pytest
from sqlalchemy.orm import Session

import tools.agents as agents
from tools import functions as tools
from tools.agents import schemas
from tools.core.models import ProposedChange, Rule, RuleSet

pytestmark = pytest.mark.agents


@pytest.fixture(scope="module")
def stub_model():
    from components.llm import build_model_for_env

    model = build_model_for_env()
    assert type(model).__name__ == "StubLlm", "tests must run with CCRE_LLM_MODE=stub"
    return model


def _tool_names(agent) -> set[str]:
    return {getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools}


# --------------------------------------------------------------------------- #
# The tool boundary
# --------------------------------------------------------------------------- #

def test_only_one_tool_can_write_anything() -> None:
    """Read tools must not mutate. Staging is the single write path."""
    assert tools.PROPOSE_TOOLS == [tools.stage_change_set]
    assert tools.stage_change_set not in tools.READ_TOOLS


def test_no_tool_can_approve_transition_or_reach_ccre() -> None:
    """The dangerous verbs simply have no implementation to call."""
    exposed = {fn.__name__ for fn in tools.READ_TOOLS + tools.PROPOSE_TOOLS}
    for forbidden in (
        "approve", "sign_off", "signoff", "fire_transition", "transition",
        "upload", "deploy", "execute_dmg", "write_rule", "update_rule", "seal",
    ):
        assert not any(forbidden in name for name in exposed), forbidden


def test_every_tool_is_documented_for_the_model() -> None:
    """ADK derives the tool contract from the signature and docstring."""
    for fn in tools.READ_TOOLS + tools.PROPOSE_TOOLS:
        doc = inspect.getdoc(fn)
        assert doc, f"{fn.__name__} has no docstring"
        assert "Returns:" in doc, f"{fn.__name__} does not document its return"
        for name, param in inspect.signature(fn).parameters.items():
            assert param.annotation is not inspect.Parameter.empty, f"{fn.__name__}({name}) is unannotated"


def test_check_expression_tool_guides_toward_the_fix() -> None:
    result = tools.check_expression('matchCiMask("shortCode,==,SDT")')
    assert result["errors"]
    assert any("|" in e for e in result["errors"])
    assert "matchCiMask" in result["known_functions"]
    assert "serviceCodeList" in result["known_lists"]


def test_check_expression_tool_accepts_the_corrected_form() -> None:
    corrected = 'matchCiMask("shortCode|==|SDT","value|!=|<blank>")&& !serviceCodeList.contains("DD")'
    result = tools.check_expression(corrected)
    assert result["parses"]
    assert result["errors"] == []
    assert result["normalised"]


def test_stage_change_set_rejects_malformed_input() -> None:
    result = tools.stage_change_set("case-1", "{not json")
    assert result["staged"] is False
    assert "error" in result


def test_list_rule_sets_tool_returns_both_lists() -> None:
    result = tools.list_rule_sets()
    assert set(result) == {"rule_sets", "cases"}


# --------------------------------------------------------------------------- #
# Output schemas
# --------------------------------------------------------------------------- #

def test_interpretation_flags_its_own_uncertainty() -> None:
    confident = schemas.RequirementInterpretation(
        country_code="BG", shipment_type="B2C", requirement_groups=["IOSS"], confidence="high",
    )
    assert not confident.needs_clarification
    for uncertain in (
        schemas.RequirementInterpretation(ambiguities=["is SDT presence or absence meant?"]),
        schemas.RequirementInterpretation(missing_information=["no effective date given"]),
        schemas.RequirementInterpretation(confidence="low"),
    ):
        assert uncertain.needs_clarification


def test_interpretation_models_presence_not_equality() -> None:
    """The BG correction turned on exactly this distinction."""
    interpretation = schemas.RequirementInterpretation(
        country_code="BG", shipment_type="B2C", requirement_groups=["IOSS"],
        conditions=[
            schemas.Condition(field="service_code", operator="not_contains", value="DD"),
            schemas.Condition(field="SDT", operator="present"),
        ],
    )
    sdt = next(c for c in interpretation.conditions if c.field == "SDT")
    assert sdt.operator == "present"
    assert sdt.value is None


def test_failure_analysis_defaults_to_not_touching_rules() -> None:
    analysis = schemas.FailureAnalysis(
        test_id="TC-01", likely_cause="SDT absent from the payload",
        category="payload", recommended_action="Add SDT to the test payload and re-run",
    )
    assert analysis.change_rules is False


def test_validators_reject_bad_agent_output() -> None:
    from server.artifact_schemas import (
        validate_change_set, validate_failure_analysis, validate_interpretation, validate_test_suite,
    )

    with pytest.raises(TypeError):
        validate_interpretation(["not", "an", "object"])
    with pytest.raises(ValueError):
        validate_change_set({"summary": "empty", "rules": []})
    with pytest.raises(ValueError):
        validate_test_suite({"summary": "empty", "cases": []})
    with pytest.raises(Exception):
        validate_failure_analysis({"test_id": "x", "category": "made_up"})


# --------------------------------------------------------------------------- #
# Proposals are inert until accepted
# --------------------------------------------------------------------------- #

def test_proposal_does_not_become_a_rule_until_accepted(session: Session) -> None:
    session.add(RuleSet(version="v0.1"))
    session.add(ProposedChange(
        case_id="case-1", origin="rule_drafter", status="PROPOSED",
        payload={"summary": "BG", "rules": [{"ctry_cd": "BG", "sirg_cd": "IOSS"}]},
    ))
    session.commit()
    assert session.query(ProposedChange).count() == 1
    assert session.query(Rule).count() == 0


def test_stage_proposal_writes_only_the_staging_table(session: Session) -> None:
    change_set = schemas.ChangeSet(
        summary="BG phase 1",
        rules=[schemas.ProposedRule(ctry_cd="BG", sirg_cd="IOSS", other_logic='matchCiMask("a,==,b")')],
    )
    result = tools.stage_proposal(session, "case-1", change_set, origin="rule_drafter")
    session.commit()
    assert result["staged"] and result["status"] == "PROPOSED"
    assert result["expression_diagnostics"], "the comma-delimited mask must be flagged at staging"
    assert session.query(Rule).count() == 0


# --------------------------------------------------------------------------- #
# Agent construction
# --------------------------------------------------------------------------- #

def test_agent_specs_declare_a_gate_each() -> None:
    assert set(agents.AGENT_SPECS) == {
        "intake_assistant", "requirement_interpreter", "timeline_planner", "rule_drafter",
        "test_case_designer", "payload_generator", "response_reviewer", "failure_analyst",
    }
    for name, spec in agents.AGENT_SPECS.items():
        assert spec["gate"], f"{name} declares no human gate"
        assert spec["output"]


def test_importing_the_advisory_layer_needs_no_credential() -> None:
    available, reason = agents.agents_available()
    assert isinstance(available, bool)
    if not available:
        assert reason


def test_no_sub_agent_holds_a_write_tool(stub_model) -> None:
    built = {
        "requirement_interpreter": agents.build_requirement_interpreter_agent(stub_model),
        "rule_drafter": agents.build_rule_drafter_agent(stub_model),
        "test_case_designer": agents.build_test_case_designer_agent(stub_model),
        "failure_analyst": agents.build_failure_analyst_agent(stub_model),
    }
    for name, agent in built.items():
        assert agent.name == name
        assert "stage_change_set" not in _tool_names(agent), f"{name} must not stage changes"
    assert "check_expression" in _tool_names(built["rule_drafter"])


def test_agent_instructions_state_the_hard_rules(stub_model) -> None:
    for build in (
        agents.build_requirement_interpreter_agent, agents.build_rule_drafter_agent,
        agents.build_test_case_designer_agent, agents.build_failure_analyst_agent,
    ):
        agent = build(stub_model)
        assert f"You are **{agent.name}**" in agent.instruction
        assert "Humans approve" in agent.instruction, f"{agent.name} omits the approval rule"
        assert "Never invent" in agent.instruction, f"{agent.name} omits the no-invention rule"


def test_root_agent_wires_every_sub_agent_and_no_write_tool() -> None:
    import agent as entry

    names = _tool_names(entry.root_agent)
    assert set(entry.ROOT_DELEGATES) <= names
    # Lifecycle-only agents are invoked by the server, not by the chat orchestrator.
    assert not {"intake_assistant", "payload_generator", "response_reviewer"} & names
    assert "validate_rule_set" in names and "check_expression" in names
    assert "stage_change_set" not in names


# --------------------------------------------------------------------------- #
# Real ADK runs with the stub LLM
# --------------------------------------------------------------------------- #

def test_interpreter_run_returns_a_valid_interpretation() -> None:
    import agent as entry
    from server.agent_invoker import invoke_agent
    from server.artifact_schemas import validate_interpretation

    data = invoke_agent(
        entry.requirement_interpreter,
        "BG B2C shipments need IOSS when SDT is present and the service code is not DD.",
        session_id="t_interp", validate=validate_interpretation,
    )
    assert data["country_code"] == "BG"
    assert "IOSS" in data["requirement_groups"]
    assert any(c["field"] == "SDT" and c["operator"] == "present" for c in data["conditions"])


def test_rule_drafter_run_returns_a_valid_change_set() -> None:
    import agent as entry
    from server.agent_invoker import invoke_agent
    from server.artifact_schemas import validate_change_set

    data = invoke_agent(entry.rule_drafter, "Draft rules for BG IOSS.",
                        session_id="t_draft", validate=validate_change_set)
    assert data["rules"][0]["ctry_cd"] == "BG"
    assert data["rules"][0]["sirg_cd"] == "IOSS"


def test_root_agent_delegates_to_a_sub_agent() -> None:
    import agent as entry
    from server.agent_invoker import run_text

    reply = run_text(entry.root_agent, "BG needs IOSS when SDT is present", session_id="t_root")
    assert "requirement_interpreter" in reply
    assert "IOSS" in reply


def test_root_agent_calls_a_database_tool() -> None:
    import agent as entry
    from server.agent_invoker import run_text

    reply = run_text(entry.root_agent, 'Check: matchCiMask("shortCode,==,SDT")', session_id="t_expr")
    assert "check_expression" in reply
    assert "pipe" in reply.lower() or "|" in reply


def test_all_eight_agents_are_built_with_the_house_rules() -> None:
    import agent as entry

    assert len(entry.SUB_AGENTS) == 8
    for name, built in entry.SUB_AGENTS.items():
        assert built.name == name
        assert f"You are **{name}**" in built.instruction
        assert "Humans approve" in built.instruction
        assert "stage_change_set" not in _tool_names(built)


def test_timeline_planner_returns_the_seven_milestones() -> None:
    import agent as entry
    from server.agent_invoker import invoke_agent
    from tools.timeline import estimate, normalise_answers

    answers = normalise_answers({"requested_rtp": "2027-01-29", "earliest_start": "2026-11-02"})
    baseline = estimate({"group_count": 1, "condition_count": 1, "country_in_package": True}, answers)
    prompt = "Baseline estimate:\n```json\n" + json.dumps(baseline) + "\n```"
    plan = invoke_agent(entry.timeline_planner, prompt, session_id="t_tl")
    assert [m["stage"] for m in plan["milestones"]][-1] == "RTP"
    assert len(plan["milestones"]) == 7


def test_payload_generator_and_reviewer_round_trip() -> None:
    from server.advisory import AdvisoryService
    from tools.execution import builtin_sample_payload, check_response

    service = AdvisoryService()
    case = {"test_id": "DE-POA-01P", "input_conditions": [{"field": "incoterm", "operator": "equals",
                                                            "value": "DDP"}],
            "expected_requirement": "POA", "expected_case_created": True}
    generated = service.generate_payload(builtin_sample_payload(), case, [], "DE")
    assert generated["payload"]["incoterm"] == "DDP"
    assert generated["payload"]["destinationCountry"] == "DE"
    body = {"caseCreated": True, "requirements": [{"group": "POA"}]}
    check = check_response(body, 200, "POA", True)
    review = service.review_response(case, generated["payload"], 200, body, check)
    assert review["verdict"] == "PASS" and review["business_explanation"]
