"""Deterministic check of an execution response against the test expectation.

The response shape is configurable, because the real CCRE response format is
owned by the endpoint:

* ``CCRE_UAT_GROUPS_PATH`` (default ``requirements[].group``) — where the raised
  requirement group codes are.
* ``CCRE_UAT_CASE_CREATED_PATH`` (default ``caseCreated``) — whether a case was created.

When both paths resolve, the verdict is decided here, by code. When they do not,
the check is *inconclusive* and the AI ``response_reviewer`` decides, marked as such.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from tools.agents.harness.errors import GateResult

_MISSING = object()


def resolve(body: Any, path: str) -> Any:
    """Resolve a dotted path with ``[]`` list fan-out, e.g. ``requirements[].group``."""
    current: list[Any] = [body]
    fanned = False
    for part in [p for p in path.split(".") if p]:
        fan_out = part.endswith("[]")
        name = part[:-2] if fan_out else part
        nxt: list[Any] = []
        found = False
        for item in current:
            value = item.get(name, _MISSING) if isinstance(item, dict) else _MISSING
            if value is _MISSING:
                continue
            if fan_out:
                if not isinstance(value, list):
                    continue
                found = True
                nxt.extend(value)
            else:
                found = True
                nxt.append(value)
        if not found and not (fanned and not current):
            return _MISSING  # the key is genuinely absent
        fanned = fanned or fan_out
        current = nxt
    # After a fan-out an empty list is a real answer ("none raised"), not a miss.
    return current if fanned else (current[0] if current else _MISSING)


def check_response(body: Any, status: Optional[int], expected_requirement: Optional[str],
                   expected_case_created: bool, *, groups_path: Optional[str] = None,
                   case_path: Optional[str] = None, status_path: Optional[str] = None,
                   status_ok: Optional[str] = None) -> dict[str, Any]:
    """Decide PASS/FAIL from the response when it can be read.

    Paths come from the Admin endpoint configuration; without one, from the
    environment (``CCRE_UAT_GROUPS_PATH`` / ``CCRE_UAT_CASE_CREATED_PATH``). An empty
    ``case_path`` means "a case is created when anything is raised". ``status_path``
    + ``status_ok`` check the service's own success indicator first.
    """
    groups_path = groups_path or os.getenv("CCRE_UAT_GROUPS_PATH", "requirements[].group")
    if case_path is None:
        case_path = os.getenv("CCRE_UAT_CASE_CREATED_PATH", "caseCreated")

    if status is None or status >= 400:
        return {"conclusive": True, "passed": False, "outcome": "fail",
                "reason_code": "NO_RESPONSE" if status is None else "HTTP_ERROR",
                "reasons": [f"Endpoint returned {'no response' if status is None else f'HTTP {status}'}."]}

    if status_path and status_ok not in (None, ""):
        found = resolve(body, status_path)
        values = found if isinstance(found, list) else ([] if found is _MISSING else [found])
        if not any(str(v) == str(status_ok) for v in values):
            shown = ", ".join(str(v) for v in values) or "not present"
            return {"conclusive": True, "passed": False, "outcome": "fail", "reason_code": "SERVICE_STATUS_NOT_OK",
                    "reasons": [f"The service did not report success ({status_path} = {shown}; "
                                f"expected {status_ok})."]}

    groups = resolve(body, groups_path)
    case_created = resolve(body, case_path) if case_path else None
    if groups is _MISSING or case_created is _MISSING:
        missing = [p for p, v in ((groups_path, groups), (case_path, case_created)) if v is _MISSING]
        return {"conclusive": False, "passed": None, "outcome": "undecided", "reason_code": "PATH_NOT_FOUND",
                "missing_paths": missing,
                "reasons": [f"Could not find {', '.join(missing)} in the response."]}

    raised = sorted({str(g).upper() for g in (groups if isinstance(groups, list) else [groups]) or []
                     if g not in (None, "", "-")})
    if not case_path:
        case_created = bool(raised)
    reasons: list[str] = []
    passed = True
    reason_code = "AS_EXPECTED"
    if expected_requirement:
        # A test about one group: pass/fail is whether *that* group was raised.
        # Other groups legitimately raised for the country do not fail it.
        want = expected_requirement.upper()
        if expected_case_created and want not in raised:
            passed, reason_code = False, "EXPECTED_NOT_RAISED"
            reasons.append(f"Expected {want} to be raised; raised: {', '.join(raised) or 'none'}.")
        if not expected_case_created and want in raised:
            passed, reason_code = False, "UNEXPECTED_RAISED"
            reasons.append(f"{want} was raised but should not have been.")
    elif bool(case_created) != bool(expected_case_created):
        passed, reason_code = False, "CASE_FLAG_MISMATCH"
        reasons.append(f"Expected case created = {expected_case_created}, got {bool(case_created)}.")
    if passed:
        reasons.append(f"Raised: {', '.join(raised) or 'none'}; case created = {bool(case_created)} — as expected.")
    return {"conclusive": True, "passed": passed, "outcome": "pass" if passed else "fail",
            "reason_code": reason_code, "raised": raised,
            "case_created": bool(case_created), "reasons": reasons}


_CHECK_HINTS: dict[str, str] = {
    "NO_RESPONSE": "Check the endpoint is reachable (environment problem, not a rule defect).",
    "HTTP_ERROR": "Check the endpoint URL, credentials and payload; the service rejected the call.",
    "SERVICE_STATUS_NOT_OK": "Read the service's status message; the request was not processed.",
    "PATH_NOT_FOUND": "The response shape differs from the configured paths; the response_reviewer decides, "
                      "or fix the endpoint's paths in Admin.",
    "EXPECTED_NOT_RAISED": "Check the rule row's conditions and bindings against the payload values.",
    "UNEXPECTED_RAISED": "Check the rule's exclusions (Other Logic) and the test expectation.",
    "CASE_FLAG_MISMATCH": "Check whether the test expectation or the rule is wrong.",
}


def gate_check(result: dict[str, Any]) -> "GateResult":
    """A :func:`check_response` result as a :class:`GateResult` (docs/adr/0002).

    ``pass`` -> passed; ``fail`` and ``undecided`` -> one error whose code is
    ``UAT_<REASON_CODE>``. Undecided is never a pass: it routes to the reviewer.
    """
    from tools.agents.harness.errors import GateError, GateResult

    outcome = result.get("outcome")
    if outcome == "pass":
        return GateResult.ok()
    code = result.get("reason_code") or ("PATH_NOT_FOUND" if outcome == "undecided" else "FAILED")
    path = ", ".join(result.get("missing_paths") or []) or "response"
    return GateResult.from_errors([GateError(code=f"UAT_{code}", path=path,
                                             message=" ".join(result.get("reasons") or [outcome or "failed"]),
                                             hint=_CHECK_HINTS.get(code))])
