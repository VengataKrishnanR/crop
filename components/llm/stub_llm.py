"""Stub LLM for local testing without the DHL Apigee proxy.

Returns scripted, agent-aware responses so the full agent flow can be exercised
end-to-end without real HTTP calls or API keys.

Usage:
    Set  CCRE_LLM_MODE=stub  in your .env and run as normal. Every agent answers
    instantly with deterministic, schema-valid output. The root orchestrator emits
    real functionCall parts, so ADK genuinely invokes the sub-agents and the
    read-only FunctionTools (which query the real database).
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

# ---------------------------------------------------------------------------
# Role detection — read the system instruction to identify which agent is
# speaking, then dispatch to the right canned response.
# ---------------------------------------------------------------------------

_ROLE_HINTS: dict[str, list[str]] = {
    # Root checked FIRST — its prompt names every sub-agent.
    "ccre_orchestrator": ["You are **ccre_orchestrator**"],
    "requirement_interpreter": ["You are **requirement_interpreter**"],
    "rule_drafter": ["You are **rule_drafter**"],
    "test_case_designer": ["You are **test_case_designer**"],
    "failure_analyst": ["You are **failure_analyst**"],
    "intake_assistant": ["You are **intake_assistant**"],
    "timeline_planner": ["You are **timeline_planner**"],
    "payload_generator": ["You are **payload_generator**"],
    "response_reviewer": ["You are **response_reviewer**"],
}

_COUNTRY = re.compile(r"\b([A-Z]{2})\b")
_GROUP = re.compile(r"\b([A-Z][A-Z0-9]{3})\b")
# Two-letter tokens that are never meant as a country here (real ISO codes such as
# AT, IT, IN, NO and BE are deliberately NOT listed).
_NOT_COUNTRY = {"IF", "OR", "OF", "ON", "DD", "OK", "PM", "AI"}
_NOT_GROUP = {"WHEN", "THEN", "WITH", "THIS", "THAT", "FROM", "MUST", "NEED", "RULE", "TEST", "JSON",
              "USER", "CCRE", "NONE", "TRUE", "NULL", "DEMO", "CASE", "ALSO", "ONLY"}


def _detect_role(llm_request: LlmRequest) -> str:
    """Identify which agent is invoking the LLM from its system instruction."""
    si = getattr(llm_request.config, "system_instruction", None) if llm_request.config else None
    si_text = ""
    if si:
        if isinstance(si, str):
            si_text = si
        else:
            for part in getattr(si, "parts", []) or []:
                if getattr(part, "text", None):
                    si_text += part.text
    for role, hints in _ROLE_HINTS.items():
        if any(hint in si_text for hint in hints):
            return role
    return "unknown"


def _extract_user_text(llm_request: LlmRequest) -> str:
    """Return the most recent user turn as a single string."""
    for content in reversed(llm_request.contents or []):
        if content.role == "user":
            text = " ".join(
                getattr(p, "text", "") for p in (content.parts or []) if getattr(p, "text", None)
            )
            if text.strip():
                return text
    return ""


def _country(text: str) -> str | None:
    for m in _COUNTRY.finditer(text):
        if m.group(1) not in _NOT_COUNTRY:
            return m.group(1)
    return None


def _groups(text: str) -> list[str]:
    seen: list[str] = []
    for m in _GROUP.finditer(text):
        code = m.group(1)
        if code not in _NOT_GROUP and code not in seen:
            seen.append(code)
    return seen


def _focus(text: str) -> str:
    """Drop the case header the server prepends; keep only the requirement itself."""
    for marker in ("Interpret this country requirement:", "Requirement:", "Approved interpretation:"):
        if marker in text:
            return text.rsplit(marker, 1)[1]
    return text


def _fenced(obj: dict[str, Any]) -> str:
    return "```json\n" + json.dumps(obj, indent=2) + "\n```"


# ---------------------------------------------------------------------------
# Canned responses per agent role (each is valid against tools/agents/schemas.py)
# ---------------------------------------------------------------------------

def _stub_interpretation(user_text: str) -> str:
    user_text = _focus(user_text)
    country = _country(user_text)
    groups = _groups(user_text)  # never invent a group the text does not name
    shipment = "B2C" if "B2C" in user_text else ("B2B" if "B2B" in user_text else None)
    conditions: list[dict[str, Any]] = []
    if "DD" in user_text or "DDP" in user_text:
        conditions.append({"field": "service_code", "operator": "not_contains", "value": "DD"})
    if "SDT" in user_text:
        conditions.append({"field": "SDT", "operator": "present", "value": None})
    return _fenced({
        "country_code": country,
        "shipment_type": shipment,
        "direction": "Export" if "export" in user_text.lower() else "Import",
        "requirement_groups": groups,
        "conditions": conditions,
        "expected_behaviour": f"Raise {', '.join(groups)} for {country or 'the country'} when the conditions hold.",
        "ambiguities": [] if conditions else ["No explicit trigger condition was stated."],
        "missing_information": ([] if country else ["Country code not stated."])
        + ([] if groups else ["No requirement group code is named in the text."]),
        "confidence": "medium" if country and conditions else "low",
        "reasoning": "Stub interpretation: country, groups and conditions were read from the text by pattern.",
    })


def _stub_change_set(user_text: str) -> str:
    interpretation = _json_after(user_text, "Approved interpretation") or {}
    user_text = _focus(user_text)
    country = interpretation.get("country_code") or _country(user_text) or "BG"
    groups = interpretation.get("requirement_groups") or _groups(user_text) or ["IOSS"]
    rules = [
        {
            "ctry_cd": country, "direction": "Import",
            "shipment_type": "B2C" if "B2C" in user_text else None,
            "other_logic": '!serviceCodeList.contains("DD")',
            "sirg_cd": group, "sir_id": None, "cmpt_nm": None,
            "waived_to_validate": False, "waived_if_whitelisted": False,
            "rationale": "Stub draft: minimal non-DDP trigger for the requested group.",
        }
        for group in groups
    ]
    return _fenced({
        "summary": f"{country} {', '.join(groups)} candidate rules (stub)",
        "rules": rules,
        "reuses_existing": [],
        "risks": [f"Confirm {country} is mapped in the config package before testing."],
        "open_questions": ["Stub output — rerun with a real model for a considered draft."],
    })


def _stub_failure_analysis(user_text: str) -> str:
    m = re.search(r"([A-Z]{2}-[A-Z0-9]+-[0-9A-Z]+)", user_text)
    package_gap = "not mapped" in user_text
    if package_gap:
        cause, category, action, confidence = (
            "The rule matched, but the requirement group is not mapped for the country in the config package.",
            "package_config", "Ask Support to rebuild and upload the package with the mapping, then re-run.", "high")
    elif '"verdict": "FAIL"' in user_text or "FAIL" in user_text:
        cause, category, action, confidence = (
            "The payload did not satisfy the rule conditions the test intended, or the rule condition is wrong.",
            "payload", "Compare the payload changes with the rule's Other Logic; correct the test or the M2C row.",
            "medium")
    else:
        cause, category, action, confidence = (
            "Not enough evidence to determine the cause.", "unknown",
            "Re-run the test with request/response logging.", "low")
    return _fenced({
        "test_id": m.group(1) if m else "UNKNOWN", "likely_cause": cause, "category": category,
        "evidence": ["Stub analysis based on the execution result."],
        "recommended_action": action, "change_rules": False, "confidence": confidence,
    })


def _json_after(text: str, label: str) -> Any:
    """The first ```json block that follows ``label`` in the prompt, parsed."""
    idx = text.find(label)
    if idx < 0:
        return None
    m = re.search(r"```json\s*(.*?)```", text[idx:], re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ── intake chatbot ─────────────────────────────────────────────────────────

_INTAKE_STEPS = (
    ("country", "Which country is this for? (two-letter code, e.g. BG)"),
    ("shipment_type", "Should it apply to business (B2B), consumer (B2C) shipments, or both?"),
    ("groups", "Which document or information must be requested? (e.g. IOSS, POAB)"),
    ("conditions", "When exactly should it be requested? For example: when SDT is present, "
                   "or when the service code is not DD."),
    ("requested_rtp", "What is the requested go-live date? (YYYY-MM-DD)"),
    ("business_owner", "Who is the business owner for this requirement?"),
)
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _stub_intake(user_text: str) -> str:
    turns = re.findall(r"^(USER|ASSISTANT): (.*)$", user_text, re.MULTILINE)
    facts: dict[str, Any] = {}
    asked: str | None = None
    for speaker, text in turns:
        if speaker == "ASSISTANT":
            asked = next((key for key, q in _INTAKE_STEPS if q[:30] in text), None)
            continue
        upper = text.upper()
        country = _country(text)
        if country and "country" not in facts:
            facts["country"] = country
        if "B2B" in upper and "B2C" in upper or "BOTH" in upper:
            facts["shipment_type"] = "B2B/B2C"
        elif "B2C" in upper or "CONSUMER" in upper:
            facts["shipment_type"] = "B2C"
        elif "B2B" in upper or "BUSINESS" in upper and asked == "shipment_type":
            facts["shipment_type"] = "B2B"
        groups = [g for g in _groups(text) if g != facts.get("country")]
        if groups:
            facts.setdefault("groups", [])
            facts["groups"] += [g for g in groups if g not in facts["groups"]]
        conditions = []
        if "SDT" in upper:
            conditions.append({"field": "SDT", "operator": "present", "value": None})
        if "DD" in re.findall(r"\b[A-Z]{2}\b", upper) or "DDP" in upper:
            conditions.append({"field": "service_code", "operator": "not_contains", "value": "DD"})
        if conditions:
            facts["conditions"] = conditions
        if (m := _DATE_RE.search(text)):
            facts["requested_rtp"] = m.group(1)
        if asked == "business_owner" and text.strip():
            facts["business_owner"] = text.strip()
        if asked == "conditions" and "conditions" not in facts and text.strip():
            facts["conditions"] = []  # answered, but nothing machine-readable
            facts["condition_note"] = text.strip()

    for key, question in _INTAKE_STEPS:
        if key not in facts:
            return _fenced({"reply": question, "complete": False, "requirement": None})

    groups = facts["groups"]
    requirement = {
        "country_code": facts["country"], "shipment_type": facts["shipment_type"], "direction": "Import",
        "requirement_groups": groups, "conditions": facts["conditions"],
        "expected_behaviour": f"Request {', '.join(groups)} for {facts['country']} shipments when the conditions hold.",
        "ambiguities": [] if facts["conditions"] else
        [f"Trigger stated as '{facts.get('condition_note', '')}' — needs a precise condition."],
        "missing_information": [], "confidence": "medium" if facts["conditions"] else "low",
        "reasoning": "Captured through the intake conversation (stub).",
        "summary": f"{facts['country']} {facts['shipment_type']} shipments must provide {', '.join(groups)}.",
        "requested_rtp": facts["requested_rtp"], "business_owner": facts["business_owner"],
        "sample_scenarios": [],
    }
    bullets = "\n".join([
        f"- Country: {facts['country']}", f"- Shipments: {facts['shipment_type']}",
        f"- Requirement: {', '.join(groups)}",
        f"- Trigger: {'; '.join(c['field'] + ' ' + c['operator'] + (' ' + str(c['value']) if c['value'] else '') for c in facts['conditions']) or facts.get('condition_note', '-')}",
        f"- Go-live: {facts['requested_rtp']}", f"- Business owner: {facts['business_owner']}",
    ])
    return _fenced({"reply": f"Here is what I captured:\n{bullets}\n\nPlease confirm, or tell me what to change.",
                    "complete": True, "requirement": requirement})


# ── timeline planner ───────────────────────────────────────────────────────

def _stub_timeline(user_text: str) -> str:
    baseline = _json_after(user_text, "Baseline estimate") or {}
    milestones = [
        {"stage": m["stage"], "start": m["start"], "end": m["end"],
         "notes": f"{m.get('working_days', '?')} working days (baseline)"}
        for m in baseline.get("milestones", [])
    ]
    return _fenced({"milestones": milestones, "assumptions": baseline.get("assumptions", []),
                    "risks": [], "open_questions": []})


# ── UAT test design from the M2C rules ─────────────────────────────────────

def _conditions_from_rule(rule: dict[str, Any]) -> list[dict[str, Any]]:
    logic = rule.get("other_logic") or ""
    conds: list[dict[str, Any]] = []
    for neg, code in re.findall(r'(!?)serviceCodeList\.contains\("(\w+)"\)', logic):
        conds.append({"field": "service_code", "operator": "not_contains" if neg else "contains", "value": code})
    for code in re.findall(r'matchCiMask\("shortCode\|==\|(\w+)"', logic):
        conds.append({"field": code, "operator": "present", "value": None})
    if (m := re.search(r'OriginCountry=="(\w+)"', logic)):
        conds.append({"field": "origin_country", "operator": "equals", "value": m.group(1)})
    if (m := re.search(r'incotermCodeList\.contains\("(\w+)"\)', logic)):
        conds.append({"field": "incoterm", "operator": "equals", "value": m.group(1)})
    if (m := re.search(r'destinationServiceArea\.contains\("(\w+)"\)', logic)):
        conds.append({"field": "destination_service_area", "operator": "contains", "value": m.group(1)})
    return conds


def _flip(cond: dict[str, Any]) -> dict[str, Any]:
    flipped = {"contains": "not_contains", "not_contains": "contains", "present": "absent",
               "absent": "present", "equals": "not_equals", "not_equals": "equals"}
    out = dict(cond)
    out["operator"] = flipped.get(cond["operator"], cond["operator"])
    if out["field"] == "origin_country" and out["operator"] == "not_equals":
        out = {"field": "origin_country", "operator": "equals", "value": "ZZ"}
    return out


def _base_inputs(rule: dict[str, Any]) -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    if rule.get("shipment_type"):
        inputs.append({"field": "shipment_type", "operator": "equals",
                       "value": str(rule["shipment_type"]).split("/")[0]})
    low, high = rule.get("min_value"), rule.get("max_value")
    if low is not None or high is not None:
        value = low if low is not None else 0
        if high is not None:
            value = (value + high) / 2 if low is not None else high / 2
        inputs.append({"field": "declared_value", "operator": "equals", "value": round(float(value), 2)})
    return inputs


def _stub_test_suite(user_text: str) -> str:
    rules = _json_after(user_text, "Design the test suite for these rules") or []
    if not isinstance(rules, list) or not rules:
        country = _country(user_text) or "BG"
        group = (_groups(user_text) or ["IOSS"])[0]
        rules = [{"country": country, "requirement_group": group, "other_logic": '!serviceCodeList.contains("DD")'}]
    cases: list[dict[str, Any]] = []
    for i, rule in enumerate(rules, start=1):
        country = rule.get("country") or "BG"
        group = rule.get("requirement_group") or "IOSS"
        base = _base_inputs(rule)
        conds = _conditions_from_rule(rule)
        label = f"{country} {group}"
        cases.append({
            "test_id": f"{country}-{group}-{i:02d}P", "scenario": f"All conditions of {label} hold",
            "business_summary": f"A {country} shipment that meets every condition must ask for {group}.",
            "kind": "positive", "preconditions": [f"{group} mapped for {country} in the config package"],
            "input_conditions": base + conds, "expected_requirement": group, "expected_case_created": True,
            "validation_criteria": f"{group} requirement raised", "rule_coverage": [rule.get("id") or label],
            "priority": "high",
        })
        if conds:
            first = conds[0]
            cases.append({
                "test_id": f"{country}-{group}-{i:02d}N", "scenario": f"{first['field']} flipped — must not raise {group}",
                "business_summary": f"A {country} shipment that does not meet the '{first['field']}' condition "
                                    f"must not ask for {group}.",
                "kind": "negative", "preconditions": [],
                "input_conditions": base + [_flip(first)] + conds[1:], "expected_requirement": group,
                "expected_case_created": False, "validation_criteria": f"{group} requirement not raised",
                "rule_coverage": [rule.get("id") or label], "priority": "medium",
            })
    return _fenced({"summary": f"UAT suite for {len(rules)} rule(s) (stub)", "cases": cases,
                    "uncovered_conditions": []})


# ── UAT payloads and response review ───────────────────────────────────────

def _stub_payload(user_text: str) -> str:
    from tools.execution.payload_builder import build_payload

    sample = _json_after(user_text, "Sample payload") or {}
    test_case = _json_after(user_text, "Test case") or {}
    m = re.search(r"Country under test: ([A-Z]{2})", user_text)
    return _fenced(build_payload(sample, test_case, m.group(1) if m else "BG"))


def _stub_review(user_text: str) -> str:
    check = _json_after(user_text, "Deterministic check") or {}
    test_case = _json_after(user_text, "Test case") or {}
    group = test_case.get("expected_requirement") or "the requirement"
    if check.get("conclusive"):
        verdict = "PASS" if check.get("passed") else "FAIL"
    else:
        verdict = "INCONCLUSIVE"
    explanation = {
        "PASS": f"The system behaved as the business expects for {group}.",
        "FAIL": f"The system did not behave as expected for {group}; the CCRE team will investigate.",
        "INCONCLUSIVE": "The response did not show clearly what was requested; a person must check it.",
    }[verdict]
    return _fenced({"verdict": verdict, "reasons": check.get("reasons") or ["No deterministic check available."],
                    "observed_requirements": check.get("raised") or [], "business_explanation": explanation})


_DISPATCHERS = {
    "intake_assistant": _stub_intake,
    "timeline_planner": _stub_timeline,
    "payload_generator": _stub_payload,
    "response_reviewer": _stub_review,
    "requirement_interpreter": _stub_interpretation,
    "rule_drafter": _stub_change_set,
    "test_case_designer": _stub_test_suite,
    "failure_analyst": _stub_failure_analysis,
}


# ---------------------------------------------------------------------------
# Root orchestration helpers
# ---------------------------------------------------------------------------

_EXPRESSION = re.compile(r"(!?\w+\.contains\(|matchCiMask\(|hscode\(|\w+\s*==)")


def _plan_root_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Pick the one tool the orchestrator should call for this message, if any."""
    lower = text.lower()
    if "fail" in lower:
        return "failure_analyst", {"request": text}
    if "test" in lower and ("design" in lower or "case" in lower or "suite" in lower):
        return "test_case_designer", {"request": text}
    if "draft" in lower:
        return "rule_drafter", {"request": text}
    if any(w in lower for w in ("requirement", "needs", "must", "trigger", "raise")):
        return "requirement_interpreter", {"request": text}
    if "check" in lower and _EXPRESSION.search(text):
        expr = text.split(":", 1)[1].strip() if ":" in text else text
        return "check_expression", {"expression": expr.strip("` ")}
    m = re.search(r"\b([A-Z]{2})\b", text)
    if ("package" in lower or "status" in lower) and m:
        return "country_package_status", {"country_code": m.group(1)}
    if "group" in lower:
        return "list_requirement_groups", {"country_code": m.group(1) if m else ""}
    if "rule set" in lower or "rule-set" in lower or "cases" in lower:
        return "list_rule_sets", {"country_code": ""}
    return None


def _last_function_response(llm_request: LlmRequest) -> tuple[str, Any] | None:
    for content in reversed(llm_request.contents or []):
        for part in getattr(content, "parts", None) or []:
            fr = getattr(part, "function_response", None)
            if fr is not None:
                return fr.name, fr.response
    return None


def _render_tool_result(name: str, response: Any) -> str:
    payload = response
    if isinstance(response, dict) and set(response) == {"result"}:
        payload = response["result"]
    if isinstance(payload, str):
        body = payload
    else:
        body = _fenced(payload) if isinstance(payload, dict) else json.dumps(payload, indent=2)
    return (
        f"**`{name}`** returned:\n\n{body}\n\n"
        "_Stub run (`CCRE_LLM_MODE=stub`): the tool ran for real against the database; "
        "only the wording is scripted. Nothing has been applied — a human approves every change._"
    )


def _stub_root_greeting() -> str:
    return (
        "Hello! I'm the **CCRE onboarding assistant**.\n\n"
        "Here's what I can do:\n"
        "- **Interpret** a pasted country requirement — e.g. *BG B2C needs IOSS when SDT is present and not DDP*\n"
        "- **Draft** candidate rules for an approved requirement — *Draft rules for BG IOSS*\n"
        "- **Design tests** for a rule set — *Design test cases for BG IOSS*\n"
        "- **Analyse a failure** — *Why did BG-IOSS-01 fail?*\n"
        "- **Check an expression** — *Check: matchCiMask(\"shortCode|==|SDT\")*\n"
        "- **Look up** package status or groups — *Package status for BG*\n\n"
        "What would you like to do?"
    )


def _make_function_call_response(fn_name: str, args: dict[str, Any]) -> LlmResponse:
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part(function_call=types.FunctionCall(name=fn_name, args=args))],
        ),
        finish_reason=types.FinishReason.STOP,
        turn_complete=True,
    )


def _make_text_response(text: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        finish_reason=types.FinishReason.STOP,
        turn_complete=True,
    )


# ---------------------------------------------------------------------------
# StubLlm class
# ---------------------------------------------------------------------------

class StubLlm(BaseLlm):
    """Stub LLM — scripted, agent-aware responses without any HTTP calls.

    Useful for:
      - CI/CD pipeline testing
      - Local development without DHL VPN
      - Demonstrating the flow without spending API tokens
    """

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"stub\/.*"]

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        role = _detect_role(llm_request)

        # ── Sub-agents: return their canned JSON immediately ──────────────────
        if role in _DISPATCHERS:
            yield _make_text_response(_DISPATCHERS[role](_extract_user_text(llm_request)))
            return

        # ── Root: one tool call, then summarise its result ────────────────────
        done = _last_function_response(llm_request)
        if done is not None:
            yield _make_text_response(_render_tool_result(*done))
            return

        plan = _plan_root_call(_extract_user_text(llm_request))
        if plan is None:
            yield _make_text_response(_stub_root_greeting())
            return
        yield _make_function_call_response(*plan)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_stub_model() -> StubLlm:
    """Return a StubLlm instance. No env vars or API keys required."""
    return StubLlm(model="stub/test")
