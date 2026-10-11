"""AdvisoryService — runs the CCRE sub-agents for the HTTP API.

Each method builds the agent prompt from database facts, invokes the agent with
schema validation and one repair retry (:func:`server.agent_invoker.invoke_agent`),
and writes the result to the audit trail. The rule drafter's ChangeSet is staged
as a ``ProposedChange`` here — by code, after validation — so no agent ever holds
a write tool and nothing reaches the rule tables until a human accepts it.

No web dependency: unit-testable without FastAPI.
"""
from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.agents.schemas import ChangeSet
from tools.core.models import AuditEvent, OnboardingCase, Rule, RuleSet
from tools.functions import stage_proposal

from .agent_invoker import AgentInvocationError, invoke_agent, run_text
from .artifact_schemas import (
    validate_change_set,
    validate_failure_analysis,
    validate_interpretation,
    validate_test_suite,
)

_MAX_RULES_IN_PROMPT = 40


class AdvisoryUnavailable(RuntimeError):
    """The agents cannot be built — e.g. apigee mode without an API key."""


@lru_cache(maxsize=1)
def _agent_module() -> Any:
    """Import the root ``agent`` module once. Builds the model and all agents."""
    from tools.agents import agents_available

    available, reason = agents_available()
    if not available:
        raise AdvisoryUnavailable(reason or "Advisory layer unavailable.")
    try:
        import agent  # the ADK entry point at the project root
    except KeyError as exc:  # build_model_for_env raises KeyError for a missing env var
        raise AdvisoryUnavailable(
            f"LLM not configured: environment variable {exc} is not set. "
            "Set it in .env, or use CCRE_LLM_MODE=stub for offline mode."
        ) from exc
    except Exception as exc:  # noqa: BLE001 — reported to the caller as 503
        raise AdvisoryUnavailable(f"Agents could not be built: {exc}") from exc
    return agent


def _sub_agent(name: str) -> Any:
    return _agent_module().SUB_AGENTS[name]


def root_agent() -> Any:
    return _agent_module().root_agent


def _session_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _case_header(case: OnboardingCase) -> str:
    return (
        f"Onboarding case {case.code} (id {case.id}) — country {case.ctry_cd}, "
        f"title: {case.title}, state: {case.state}."
    )


def _audit(session: Session, case_id: Optional[str], agent: str, action: str, detail: dict) -> None:
    session.add(AuditEvent(case_id=case_id, actor=f"agent:{agent}", action=action, detail=detail))


class AdvisoryService:
    """Interpret → draft → design tests → analyse failures."""

    # -- 1. requirement interpreter -----------------------------------------
    def interpret(self, session: Session, case: OnboardingCase, requirement_text: str,
                  actor: str) -> dict[str, Any]:
        prompt = (
            f"{_case_header(case)}\n\n"
            f"Interpret this country requirement:\n\n{requirement_text.strip()}"
        )
        data = invoke_agent(_sub_agent("requirement_interpreter"), prompt,
                            session_id=_session_id("interpret"), validate=validate_interpretation)
        if not case.requirement_text:
            case.requirement_text = requirement_text
        _audit(session, case.id, "requirement_interpreter", "advisory:interpretation",
               {"requested_by": actor, "interpretation": data})
        session.commit()
        needs = bool(data["ambiguities"] or data["missing_information"]) or data["confidence"] == "low"
        return {"case_id": case.id, "interpretation": data, "needs_clarification": needs,
                "gate": "A PM must approve this reading before rules are drafted."}

    # -- 2. rule drafter ------------------------------------------------------
    def draft_rules(self, session: Session, case: OnboardingCase, requirement_text: str,
                    interpretation: Optional[dict], actor: str) -> dict[str, Any]:
        text = requirement_text.strip() or (case.requirement_text or "")
        if not text and not interpretation:
            raise ValueError("Provide requirement_text or an approved interpretation.")
        prompt = f"{_case_header(case)}\n\n"
        if text:
            prompt += f"Requirement:\n{text}\n\n"
        if interpretation:
            prompt += f"Approved interpretation:\n```json\n{json.dumps(interpretation, indent=2)}\n```\n\n"
        prompt += "Draft the candidate rules as a ChangeSet."

        data = invoke_agent(_sub_agent("rule_drafter"), prompt,
                            session_id=_session_id("draft"), validate=validate_change_set)
        data["case_id"] = case.id
        staged = stage_proposal(session, case.id, ChangeSet.model_validate(data), origin="rule_drafter")
        _audit(session, case.id, "rule_drafter", "advisory:change_set_staged",
               {"requested_by": actor, "proposal_id": staged["proposal_id"],
                "rules_proposed": staged["rules_proposed"]})
        session.commit()
        return {"case_id": case.id, "change_set": data, **staged}

    # -- 3. test case designer -----------------------------------------------
    def design_tests(self, session: Session, rule_set: RuleSet, country: Optional[str],
                     notes: str, actor: str) -> dict[str, Any]:
        stmt = select(Rule).where(Rule.rule_set_id == rule_set.id).order_by(Rule.ctry_cd, Rule.row_no)
        if country:
            stmt = stmt.where(Rule.ctry_cd == country.upper())
        rules = list(session.execute(stmt.limit(_MAX_RULES_IN_PROMPT)).scalars())
        if not rules:
            raise ValueError("No rules in scope — pick a rule set (and country) that has rules.")
        rows = [
            {
                "id": r.id, "country": r.ctry_cd, "requirement_group": r.sirg_cd,
                "shipment_type": r.shipment_type, "currency": r.currency,
                "min_value": r.min_value, "max_value": r.max_value, "other_logic": r.other_logic,
            }
            for r in rules
        ]
        prompt = (
            f"Rule set {rule_set.version} (id {rule_set.id}). Design the test suite for these rules:\n"
            f"```json\n{json.dumps(rows, indent=2)}\n```\n"
            + (f"\nReviewer notes: {notes}\n" if notes else "")
        )
        data = invoke_agent(_sub_agent("test_case_designer"), prompt,
                            session_id=_session_id("tests"), validate=validate_test_suite)
        _audit(session, rule_set.case_id, "test_case_designer", "advisory:test_suite",
               {"requested_by": actor, "rule_set_id": rule_set.id, "cases": len(data["cases"]),
                "suite": data})
        session.commit()
        return {"rule_set_id": rule_set.id, "rules_in_scope": len(rules), "suite": data,
                "gate": "A reviewer approves the suite; approved cases become evidence."}

    # -- 4. failure analyst ----------------------------------------------------
    def analyse_failure(self, session: Session, test_id: str, expected: str, actual: str,
                        details: str, case_id: Optional[str], actor: str) -> dict[str, Any]:
        prompt = (
            f"Test {test_id} failed.\n"
            f"Expected: {expected or '(not given)'}\n"
            f"Actual: {actual or '(not given)'}\n"
            f"Details:\n{details or '(none)'}"
        )
        data = invoke_agent(_sub_agent("failure_analyst"), prompt,
                            session_id=_session_id("rca"), validate=validate_failure_analysis)
        _audit(session, case_id, "failure_analyst", "advisory:failure_analysis",
               {"requested_by": actor, "analysis": data})
        session.commit()
        return {"analysis": data,
                "gate": "Recommendation only; a human decides whether to change anything."}

    # -- conversational facade -------------------------------------------------
    def chat(self, message: str) -> str:
        return run_text(root_agent(), message, session_id=_session_id("chat"))


__all__ = ["AdvisoryService", "AdvisoryUnavailable", "AgentInvocationError"]
