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
from typing import Any, Optional

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
                   expected_case_created: bool) -> dict[str, Any]:
    groups_path = os.getenv("CCRE_UAT_GROUPS_PATH", "requirements[].group")
    case_path = os.getenv("CCRE_UAT_CASE_CREATED_PATH", "caseCreated")

    if status is None or status >= 400:
        return {"conclusive": True, "passed": False,
                "reasons": [f"Endpoint returned {'no response' if status is None else f'HTTP {status}'}."]}

    groups = resolve(body, groups_path)
    case_created = resolve(body, case_path)
    if groups is _MISSING or case_created is _MISSING:
        missing = [p for p, v in ((groups_path, groups), (case_path, case_created)) if v is _MISSING]
        return {"conclusive": False, "passed": None,
                "reasons": [f"Could not find {', '.join(missing)} in the response."]}

    raised = sorted({str(g).upper() for g in (groups or []) if g})
    reasons: list[str] = []
    passed = True
    if expected_requirement:
        # A test about one group: pass/fail is whether *that* group was raised.
        # Other groups legitimately raised for the country do not fail it.
        want = expected_requirement.upper()
        if expected_case_created and want not in raised:
            passed = False
            reasons.append(f"Expected {want} to be raised; raised: {', '.join(raised) or 'none'}.")
        if not expected_case_created and want in raised:
            passed = False
            reasons.append(f"{want} was raised but should not have been.")
    elif bool(case_created) != bool(expected_case_created):
        passed = False
        reasons.append(f"Expected case created = {expected_case_created}, got {bool(case_created)}.")
    if passed:
        reasons.append(f"Raised: {', '.join(raised) or 'none'}; case created = {bool(case_created)} — as expected.")
    return {"conclusive": True, "passed": passed, "raised": raised,
            "case_created": bool(case_created), "reasons": reasons}
