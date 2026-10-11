"""Deterministic payload builder for the built-in sample shipment shape.

Adapts the sample payload to one UAT test case by applying the test case's input
conditions. It is the stub-mode payload generator and the fallback the AI
generator is compared against; for a different payload schema (your own sample)
the AI ``payload_generator`` does the mapping and records its assumptions.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_SHORT_CODE = re.compile(r"^[A-Z0-9]{2,5}$")


def _key(field: str) -> str:
    return re.sub(r"[^a-z0-9]", "", field.lower())


_ALTERNATIVES = {
    "shipmentType": ["B2C", "B2B", "C2C"],
    "incoterm": ["DAP", "EXW", "DDP"],
    "originCountry": ["CN", "US", "GB"],
    "currency": ["EUR", "USD", "GBP"],
    "destinationServiceArea": ["XXX", "YYY"],
}


def _scalar(payload: dict[str, Any], key: str, op: str, value: Any, changes: list[dict], reason: str,
            transform=str) -> None:
    """Make ``key`` satisfy ``op value`` for a scalar field (equals / not_equals)."""
    wanted = transform(value) if value is not None else None
    if op in {"not_equals", "not_contains", "absent"}:
        current = payload.get(key)
        if current is not None and str(current).upper() != str(wanted).upper():
            return  # already different
        for alt in _ALTERNATIVES.get(key, ["OTHER"]):
            if str(alt).upper() != str(wanted).upper():
                _set(payload, key, alt, changes, reason)
                return
    else:
        _set(payload, key, wanted, changes, reason)


def _set(payload: dict[str, Any], key: str, value: Any, changes: list[dict], reason: str) -> None:
    if payload.get(key) != value:
        payload[key] = value
        changes.append({"path": key, "value": value, "reason": reason})


def build_payload(sample: dict[str, Any], test_case: dict[str, Any],
                  country: str) -> dict[str, Any]:
    """Return ``{"payload", "changes", "assumptions"}`` for one test case."""
    from .crms import build_crms_payload, is_crms_payload

    if is_crms_payload(sample):  # a real CRMS ShpPcdDetailsMsg request
        return build_crms_payload(sample, test_case, country)
    payload = copy.deepcopy(sample)
    changes: list[dict[str, Any]] = []
    assumptions: list[str] = []
    test_id = test_case.get("test_id") or "UAT"

    _set(payload, "shipmentId", f"UAT-{test_id}", changes, "unique id per test case")
    _set(payload, "destinationCountry", country.upper(), changes, "country under onboarding")

    for cond in test_case.get("input_conditions") or []:
        field = str(cond.get("field") or "")
        op = str(cond.get("operator") or "")
        value = cond.get("value")
        key = _key(field)
        reason = f"{field} {op} {value if value is not None else ''}".strip()

        if key in {"servicecode", "servicecodes", "servicecodelist"}:
            codes = [c for c in payload.get("serviceCodes", [])]
            code = str(value or "").upper()
            if op in {"contains", "equals"} and code and code not in codes:
                codes.append(code)
            elif op in {"not_contains", "not_equals", "absent"} and code in codes:
                codes.remove(code)
            _set(payload, "serviceCodes", codes, changes, reason)
        elif key in {"shipmenttype", "type"}:
            _scalar(payload, "shipmentType", op, value, changes, reason, lambda v: str(v))
        elif key in {"value", "declaredvalue", "shipmentvalue", "customsvalue"}:
            try:
                _set(payload, "declaredValue", float(value), changes, reason)
            except (TypeError, ValueError):
                assumptions.append(f"Could not use '{value}' as a value for {field}.")
        elif key in {"currency"}:
            _scalar(payload, "currency", op, value, changes, reason, lambda v: str(v).upper())
        elif key in {"weight", "weightkg"}:
            try:
                _set(payload, "weightKg", float(value), changes, reason)
            except (TypeError, ValueError):
                assumptions.append(f"Could not use '{value}' as a weight for {field}.")
        elif key in {"incoterm", "incoterms", "incotermcode"}:
            _scalar(payload, "incoterm", op, value, changes, reason, lambda v: str(v).upper())
        elif key in {"origincountry", "origin"}:
            _scalar(payload, "originCountry", op, value, changes, reason, lambda v: str(v).upper())
        elif key in {"destinationservicearea", "servicearea"}:
            _scalar(payload, "destinationServiceArea", op, value, changes, reason, lambda v: str(v).upper())
        elif _SHORT_CODE.match(field) or key in {"shortcode"}:
            code = (str(value) if key == "shortcode" else field).upper()
            entries = [e for e in payload.get("shortCodes", []) if str(e.get("shortCode")).upper() != code]
            if op in {"present", "equals", "contains"}:
                entries.append({"shortCode": code, "value": f"{code}-UAT-{test_id}"})
            _set(payload, "shortCodes", entries, changes, reason)
        else:
            assumptions.append(f"No payload field mapped for condition '{reason}'; sample value kept.")

    return {"payload": payload, "changes": changes, "assumptions": assumptions}
