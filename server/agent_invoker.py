"""Run an ADK agent once and collect its final text — or a validated JSON artifact.

``invoke_agent`` gives every structured agent one repair retry: if the reply does
not parse or fails its schema, the exact error is fed back and the agent tries
again. Auth/HTTP errors from the LLM are surfaced immediately, never retried.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

from google.adk.runners import InMemoryRunner
from google.genai import types

from .json_utils import AgentInvocationError, extract_json  # noqa: F401 — re-exported

_APP = "ccre_onboarding"
_USER = "ccre"
log = logging.getLogger(__name__)


def _timeout() -> float:
    return float(os.getenv("CCRE_AGENT_TIMEOUT_SECONDS", "120"))


def _collect_final_text(agent, prompt: str, session_id: str) -> str:
    """Run ``agent`` on ``prompt`` in a fresh in-memory session; return the last text part."""

    async def _run() -> str:
        runner = InMemoryRunner(agent=agent, app_name=_APP)
        await runner.session_service.create_session(
            app_name=_APP, user_id=_USER, session_id=session_id
        )
        msg = types.Content(role="user", parts=[types.Part(text=prompt)])

        final = ""
        event_count = 0
        async for ev in runner.run_async(user_id=_USER, session_id=session_id, new_message=msg):
            event_count += 1

            # LLM-level errors first — these are configuration problems, not content.
            error_code = getattr(ev, "error_code", None)
            if error_code:
                raise AgentInvocationError(
                    f"LLM returned {error_code}: {getattr(ev, 'error_message', None)}. "
                    "Check CCRE_LLM_MODE and, for apigee mode, APIGEE_API_KEY / APIGEE_PROXY_URL in .env."
                )

            content = getattr(ev, "content", None)
            for part in (getattr(content, "parts", None) or []) if content else []:
                if getattr(part, "text", None):
                    final = part.text
            # Do NOT fall back to ev.actions — stringifying ADK metadata produces
            # text that passes JSON extraction but fails schema validation.

        log.debug("agent %s session=%s events=%d final_len=%d",
                  getattr(agent, "name", "?"), session_id, event_count, len(final))
        return final

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout=_timeout()))
    except asyncio.TimeoutError as exc:
        raise AgentInvocationError(f"Agent invocation timeout (>{_timeout():.0f}s)") from exc


def run_text(agent, prompt: str, *, session_id: str) -> str:
    """Conversational call: return the agent's final text as-is."""
    return _collect_final_text(agent, prompt, session_id)


def invoke_agent(
    agent,
    prompt: str,
    *,
    session_id: str,
    validate: Callable[[Any], Any] | None = None,
) -> Any:
    """Run ``agent`` and return its JSON output, validated, with one repair retry."""
    last_err: Exception | None = None
    attempt_prompt = prompt

    for attempt in range(2):
        text = _collect_final_text(agent, attempt_prompt, f"{session_id}_a{attempt}")
        if not text.strip():
            last_err = AgentInvocationError("empty agent response")
        else:
            try:
                data = extract_json(text)
                return validate(data) if validate else data
            except Exception as exc:  # noqa: BLE001 — fed back to the model below
                last_err = exc
                log.info("agent %s attempt %d rejected: %s", getattr(agent, "name", "?"), attempt + 1, exc)

        # Repair prompt: include the exact validation error so the model knows what failed.
        attempt_prompt = (
            f"{prompt}\n\n"
            f"IMPORTANT — your previous response was rejected with this error: {last_err}\n"
            "Respond ONLY with one valid JSON object inside a ```json code block. "
            "All required fields must be present."
        )

    raise AgentInvocationError(f"Agent failed after retry: {last_err}")
