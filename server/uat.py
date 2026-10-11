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
from typing import Any

from sqlalchemy.orm import Session

from tools.core.models import AuditEvent, OnboardingCase, PayloadTemplate, UatResult, UatRun
from tools.execution import build_executor, check_response
from tools.workflow.case_facts import case_rule_set, correction_cycle, executable_test_cases

from .agent_invoker import AgentInvocationError

log = logging.getLogger(__name__)


def _rules_for(session: Session, rule_set_id: str, country: str) -> list[dict[str, Any]]:
    from .lifecycle import _rule_rows

    return [r for r in _rule_rows(session, rule_set_id) if r["country"] == country]


def execute_run(session: Session, advisory: Any, case: OnboardingCase, template: PayloadTemplate,
                actor: str) -> UatRun:
    rule_set = case_rule_set(session, case)
    if rule_set is None:
        raise ValueError("The case has no M2C draft to test.")
    test_cases = executable_test_cases(session, case.id)
    if not test_cases:
        raise ValueError("No business-approved test cases to execute.")

    executor = build_executor(session, rule_set.id)
    rules = _rules_for(session, rule_set.id, case.ctry_cd)
    run = UatRun(case_id=case.id, rule_set_id=rule_set.id, cycle=correction_cycle(session, case.id),
                 template_id=template.id, executor=executor.name, status="RUNNING", started_by=actor)
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
                                   tc.expected_case_created)
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

    run.status = "COMPLETED"
    run.finished_at = dt.datetime.now(dt.timezone.utc)
    session.add(AuditEvent(case_id=case.id, actor=actor, action="uat:run_completed",
                           detail={"run_id": run.id, "cycle": run.cycle, "executor": run.executor,
                                   "passed": run.passed, "failed": run.failed, "errors": run.errors}))
    session.flush()
    return run
