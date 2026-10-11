"""UAT run — payload generation, execution and review for every approved test case.

Verdict authority, in order:
1. An execution error (no response, transport failure) is ``ERROR``.
2. When the deterministic checker can read the response, it decides PASS/FAIL.
3. Otherwise the AI response reviewer decides, and the result is marked ``ai``.
The reviewer always runs, so every result carries an explanation.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from tools.core.models import (
    AuditEvent, ExecutionEndpoint, OnboardingCase, PayloadTemplate, UatComparison, UatResult, UatRun,
)
from tools.execution import build_executor, check_response
from tools.execution.crms import compare_responses
from tools.execution.executor import EndpointExecutor
from tools.workflow.case_facts import case_rule_set, correction_cycle, executable_test_cases

from .agent_invoker import AgentInvocationError

log = logging.getLogger(__name__)


def _rules_for(session: Session, rule_set_id: str, country: str) -> list[dict[str, Any]]:
    from .lifecycle import _rule_rows

    return [r for r in _rule_rows(session, rule_set_id) if r["country"] == country]


def _check_paths(endpoint: Optional[ExecutionEndpoint]) -> dict[str, Any]:
    if endpoint is None:
        return {}
    return {"groups_path": endpoint.groups_path or None, "case_path": endpoint.case_flag_path or "",
            "status_path": endpoint.status_path or None, "status_ok": endpoint.status_ok_value}


def execute_run(session: Session, advisory: Any, case: OnboardingCase, template: PayloadTemplate,
                actor: str, endpoint: Optional[ExecutionEndpoint] = None,
                compare_endpoint: Optional[ExecutionEndpoint] = None) -> UatRun:
    rule_set = case_rule_set(session, case)
    if rule_set is None:
        raise ValueError("The case has no M2C draft to test.")
    test_cases = executable_test_cases(session, case.id)
    if not test_cases:
        raise ValueError("No business-approved test cases to execute.")

    executor = build_executor(session, rule_set.id, endpoint)
    comparer = EndpointExecutor.from_endpoint(compare_endpoint) if compare_endpoint is not None else None
    compare_path = (endpoint.compare_path if endpoint is not None else None) or (
        compare_endpoint.compare_path if compare_endpoint is not None else None)
    paths = _check_paths(endpoint)
    label = executor.name + (f" vs {comparer.name}" if comparer else "")
    rules = _rules_for(session, rule_set.id, case.ctry_cd)
    run = UatRun(case_id=case.id, rule_set_id=rule_set.id, cycle=correction_cycle(session, case.id),
                 template_id=template.id, executor=label[:64], status="RUNNING", started_by=actor)
    session.add(run)
    session.flush()

    for tc in test_cases:
        expectation = {
            "test_id": tc.test_id, "scenario": tc.scenario, "kind": tc.kind,
            "input_conditions": tc.input_conditions, "expected_requirement": tc.expected_requirement,
            "expected_case_created": tc.expected_case_created, "validation_criteria": tc.validation_criteria,
        }
        result = UatResult(run_id=run.id, test_case_id=tc.id, test_id=tc.test_id,
                           verdict="ERROR", verdict_source="deterministic")
        try:
            generated = advisory.generate_payload(template.body, expectation, rules, case.ctry_cd)
        except AgentInvocationError as exc:
            result.error = f"Payload generation failed: {exc}"
            session.add(result)
            run.errors += 1
            continue

        result.payload = generated["payload"]
        result.changes = generated.get("changes", [])
        outcome = executor.execute(generated["payload"])
        result.response_status = outcome.status
        result.response_body = outcome.body
        result.latency_ms = round(outcome.latency_ms, 1)

        if outcome.error:
            result.error = outcome.error
            check = {"conclusive": True, "passed": False, "reasons": [f"Execution error: {outcome.error}"]}
        else:
            check = check_response(outcome.body, outcome.status, tc.expected_requirement,
                                   tc.expected_case_created, **paths)
        result.check = check

        try:
            review = advisory.review_response(expectation, generated["payload"], outcome.status,
                                              outcome.body, check)
        except AgentInvocationError as exc:
            review = {"verdict": "INCONCLUSIVE", "reasons": [f"Reviewer failed: {exc}"],
                      "observed_requirements": [], "business_explanation": None}
        result.review = review

        if outcome.error:
            result.verdict, result.verdict_source = "ERROR", "deterministic"
        elif check.get("conclusive"):
            result.verdict = "PASS" if check.get("passed") else "FAIL"
            result.verdict_source = "deterministic"
        else:
            result.verdict, result.verdict_source = review.get("verdict", "INCONCLUSIVE"), "ai"

        if result.verdict == "PASS":
            run.passed += 1
        elif result.verdict == "ERROR":
            run.errors += 1
        else:
            run.failed += 1
        session.add(result)
        session.flush()

        if comparer is not None:
            other = comparer.execute(generated["payload"])
            diff = (compare_responses(outcome.body, other.body, compare_path)
                    if not (outcome.error or other.error) else
                    {"identical": False, "summary": {}, "differences": []})
            session.add(UatComparison(
                result_id=result.id, endpoint_name=comparer.name, response_status=other.status,
                response_body=other.body, identical=bool(diff.get("identical")),
                summary=diff.get("summary", {}), differences=diff.get("differences", []),
                error=other.error or outcome.error))

    run.status = "COMPLETED"
    run.finished_at = dt.datetime.now(dt.timezone.utc)
    session.add(AuditEvent(case_id=case.id, actor=actor, action="uat:run_completed",
                           detail={"run_id": run.id, "cycle": run.cycle, "executor": run.executor,
                                   "endpoint": endpoint.url if endpoint is not None else None,
                                   "passed": run.passed, "failed": run.failed, "errors": run.errors}))
    session.flush()
    return run
