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
}

_COUNTRY = re.compile(r"\b([A-Z]{2})\b")
_GROUP = re.compile(r"\b([A-Z][A-Z0-9]{3})\b")
_NOT_COUNTRY = {"IF", "OR", "AND", "IS", "IT", "TO", "ON", "IN", "OF", "AN", "AS", "AT", "BE", "NO", "DD", "ID"}
_NOT_GROUP = {"WHEN", "THEN", "WITH", "THIS", "THAT", "FROM", "MUST", "NEED", "RULE", "TEST", "JSON", "B2B", "B2C"}


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
    groups = _groups(user_text) or ["IOSS"]
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
        "missing_information": [] if country else ["Country code not stated."],
        "confidence": "medium" if country and conditions else "low",
        "reasoning": "Stub interpretation: country, groups and conditions were read from the text by pattern.",
    })


def _stub_change_set(user_text: str) -> str:
    user_text = _focus(user_text)
    country = _country(user_text) or "BG"
    groups = _groups(user_text) or ["IOSS"]
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


def _stub_test_suite(user_text: str) -> str:
    country = _country(user_text) or "BG"
    group = (_groups(user_text) or ["IOSS"])[0]
    return _fenced({
        "summary": f"{country} {group} coverage (stub)",
        "cases": [
            {
                "test_id": f"{country}-{group}-01", "scenario": "Trigger condition holds",
                "kind": "positive", "preconditions": [f"{country} mapped in the package"],
                "input_conditions": [{"field": "service_code", "operator": "not_contains", "value": "DD"}],
                "expected_requirement": group, "expected_case_created": True,
                "validation_criteria": f"{group} requirement raised", "rule_coverage": [f"{country} {group}"],
                "priority": "high",
            },
            {
                "test_id": f"{country}-{group}-02", "scenario": "Service code DD present",
                "kind": "negative", "preconditions": [],
                "input_conditions": [{"field": "service_code", "operator": "contains", "value": "DD"}],
                "expected_requirement": None, "expected_case_created": False,
                "validation_criteria": f"{group} requirement not raised", "rule_coverage": [f"{country} {group}"],
                "priority": "medium",
            },
        ],
        "uncovered_conditions": [],
    })


def _stub_failure_analysis(user_text: str) -> str:
    m = re.search(r"\b([A-Z]{2}-[A-Z0-9]+-\d+)\b", user_text)
    return _fenced({
        "test_id": m.group(1) if m else "UNKNOWN",
        "likely_cause": "The country is not mapped in the config package, so the requirement cannot be raised.",
        "category": "package_config",
        "evidence": ["Stub analysis — check country_package_status for the country under test."],
        "recommended_action": "Confirm the package mapping before changing any rule.",
        "change_rules": False,
        "confidence": "low",
    })


_DISPATCHERS = {
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
