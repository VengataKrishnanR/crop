"""AdvisoryService — the one place the server invokes agents.

Each method builds the agent prompt from facts it is given, invokes the agent
with schema validation and one repair retry (:func:`server.agent_invoker.invoke_agent`)
and returns plain JSON-safe dicts. Persistence, audit and state transitions are
the callers' job (:mod:`server.lifecycle`), except :meth:`draft_rules`, which
stages its ChangeSet as a ``ProposedChange`` — by code, after validation — so no
agent ever holds a write tool.

No web dependency: unit-testable without FastAPI.
"""
from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Any, Optional

from sqlalchemy.orm import Session

from tools.agents.schemas import (
    BusinessRequirement,
    ChangeSet,
    GeneratedPayload,
    IntakeTurn,
    ResponseReview,
    TimelinePlan,
)
from tools.core.models import AuditEvent, OnboardingCase
from tools.functions import stage_proposal
from tools.timeline import validate_plan

from .agent_invoker import AgentInvocationError, invoke_agent, run_text
from .artifact_schemas import (
    validate_change_set,
    validate_failure_analysis,
    validate_interpretation,
    validate_test_suite,
)


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


def _sid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _block(label: str, obj: Any) -> str:
    return f"{label}:\n```json\n{json.dumps(obj, indent=2, default=str)}\n```\n"


def _case_header(case: OnboardingCase) -> str:
    return (
        f"Onboarding case {case.code} (id {case.id}) — country {case.ctry_cd}, "
        f"title: {case.title}, state: {case.state}."
    )


def _validated(model: Any) -> Any:
    def _check(d: Any) -> dict:
        if not isinstance(d, dict):
            raise TypeError(f"{model.__name__} must be a JSON object, got {type(d).__name__}")
        return model.model_validate(d).model_dump(mode="json")
    return _check


class AdvisoryService:
    """Agent calls for every lifecycle step."""

    # -- intake: chatbot ------------------------------------------------------
    def intake_turn(self, case: OnboardingCase, transcript: list[tuple[str, str]]) -> dict[str, Any]:
        lines = "\n".join(f"{role.upper()}: {' '.join(text.split())}" for role, text in transcript)
        prompt = (
            f"{_case_header(case)}\n\n"
            f"Conversation so far:\n{lines}\n\n"
            "Reply to the latest USER message as the intake assistant."
        )
        return invoke_agent(_sub_agent("intake_assistant"), prompt, session_id=_sid("intake"),
                            validate=_validated(IntakeTurn))

    # -- intake: form + NLP -----------------------------------------------------
    def interpret_form(self, case: OnboardingCase, form: dict[str, Any], free_text: str) -> dict[str, Any]:
        prompt = (
            f"{_case_header(case)}\n\n"
            + _block("Structured fields the business team filled in (authoritative)", form)
            + f"\nInterpret this country requirement:\n\n{free_text.strip()}"
        )
        reading = invoke_agent(_sub_agent("requirement_interpreter"), prompt,
                               session_id=_sid("interpret"), validate=validate_interpretation)
        # The form fields the user typed win over the model's reading of the text.
        merged = {**reading}
        for key in ("country_code", "shipment_type", "direction"):
            if form.get(key):
                merged[key] = form[key]
        if form.get("requirement_groups"):
            merged["requirement_groups"] = sorted({*form["requirement_groups"], *reading.get("requirement_groups", [])})
        for key in ("requested_rtp", "value_threshold", "currency", "business_owner"):
            if form.get(key) not in (None, ""):
                merged[key] = form[key]
        merged["summary"] = form.get("summary") or reading.get("expected_behaviour")
        merged.setdefault("sample_scenarios", [])
        return BusinessRequirement.model_validate(merged).model_dump(mode="json")

    # -- timeline -----------------------------------------------------------------
    def plan_timeline(self, case: OnboardingCase, requirement: dict[str, Any], facts: dict[str, Any],
                      answers: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            f"{_case_header(case)}\n\n"
            + _block("Approved business requirement", requirement)
            + _block("Complexity facts", facts)
            + _block("PM questionnaire answers", answers)
            + _block("Baseline estimate", baseline)
            + "\nProduce the TimelinePlan."
        )

        def _check(d: Any) -> dict:
            plan = _validated(TimelinePlan)(d)
            plan["risk"] = validate_plan(plan["milestones"], answers)
            return plan

        return invoke_agent(_sub_agent("timeline_planner"), prompt, session_id=_sid("timeline"),
                            validate=_check)

    # -- M2C draft (rule config) --------------------------------------------------
    def draft_rules(self, session: Session, case: OnboardingCase, requirement_text: str,
                    interpretation: Optional[dict], actor: str) -> dict[str, Any]:
        text = requirement_text.strip() or (case.requirement_text or "")
        if not text and not interpretation:
            raise ValueError("Provide requirement_text or an approved interpretation.")
        prompt = f"{_case_header(case)}\n\n"
        if text:
            prompt += f"Requirement:\n{text}\n\n"
        if interpretation:
            prompt += _block("Approved interpretation", interpretation) + "\n"
        prompt += "Convert the business requirement into M2C rule rows as a ChangeSet."

        data = invoke_agent(_sub_agent("rule_drafter"), prompt,
                            session_id=_sid("draft"), validate=validate_change_set)
        data["case_id"] = case.id
        staged = stage_proposal(session, case.id, ChangeSet.model_validate(data), origin="rule_drafter")
        session.add(AuditEvent(case_id=case.id, actor="agent:rule_drafter", action="advisory:change_set_staged",
                               detail={"requested_by": actor, "proposal_id": staged["proposal_id"],
                                       "rules_proposed": staged["rules_proposed"]}))
        session.commit()
        return {"case_id": case.id, "change_set": data, **staged}

    # -- UAT test case design -------------------------------------------------------
    def design_tests(self, rule_set_version: str, rows: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
        prompt = (
            f"M2C draft {rule_set_version}. "
            + _block("Design the test suite for these rules", rows)
            + (f"\nReviewer notes: {notes}\n" if notes else "")
        )
        return invoke_agent(_sub_agent("test_case_designer"), prompt, session_id=_sid("tests"),
                            validate=validate_test_suite)

    # -- UAT execution ---------------------------------------------------------------
    def generate_payload(self, sample: dict[str, Any], test_case: dict[str, Any],
                         rules: list[dict[str, Any]], country: str) -> dict[str, Any]:
        prompt = (
            _block("Sample payload", sample)
            + _block("Test case", test_case)
            + _block("Rules under test", rules)
            + f"\nCountry under test: {country}\n\nProduce the GeneratedPayload."
        )
        return invoke_agent(_sub_agent("payload_generator"), prompt, session_id=_sid("payload"),
                            validate=_validated(GeneratedPayload))

    def review_response(self, test_case: dict[str, Any], payload: dict[str, Any], status: Optional[int],
                        body: Any, check: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            _block("Test case", test_case)
            + _block("Payload sent", payload)
            + f"\nHTTP status: {status}\n\n"
            + _block("Response body", body)
            + _block("Deterministic check", check)
            + "\nProduce the ResponseReview."
        )
        return invoke_agent(_sub_agent("response_reviewer"), prompt, session_id=_sid("review"),
                            validate=_validated(ResponseReview))

    # -- UAT review --------------------------------------------------------------------
    def analyse_failure(self, evidence: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            f"Test {evidence.get('test_id')} did not pass.\n\n"
            + _block("Execution evidence", evidence)
            + "\nProduce the FailureAnalysis."
        )
        return invoke_agent(_sub_agent("failure_analyst"), prompt, session_id=_sid("rca"),
                            validate=validate_failure_analysis)

    # -- conversational facade -----------------------------------------------------------
    def chat(self, message: str) -> str:
        return run_text(root_agent(), message, session_id=_sid("chat"))


__all__ = ["AdvisoryService", "AdvisoryUnavailable", "AgentInvocationError"]
