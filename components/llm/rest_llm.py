"""
REST-based LLM factories for the DHL GenAI Gateway.

Two providers, two request formats, one generic router:

  VertexAiRestLlm   — Gemini GenerateContent format
    POST {APIGEE_PROXY_URL}/vertexai/publishers/google/models/{id}:generateContent
    POST {APIGEE_PROXY_URL}/vertexai/publishers/google/models/{id}:streamGenerateContent  (streaming)
    Authorization: Bearer {APIGEE_API_KEY}

  AzureOpenAiRestLlm — OpenAI ChatCompletion format
    POST {APIGEE_PROXY_URL}/openai/deployments/{id}/chat/completions?api-version={ver}
    Authorization: Bearer {APIGEE_API_KEY}

Public factories
----------------
  build_vertex_ai_rest_model(deployment_id?, streaming?)  – Vertex AI only
  build_azure_rest_model(deployment_id?, streaming?)      – Azure OpenAI only
  build_rest_model(deployment_id?, streaming?)            – auto-routes via model registry

Streaming control (precedence: factory param > env var)
  APIGEE_STREAMING_ENABLED=true   – enable streaming globally (default: false)
  Or pass streaming=True to any factory to override per-instance.
  At call time, ADK may also pass stream=True to generate_content_async; either
  the instance flag or the call-time flag activates streaming.

Env vars
--------
  APIGEE_API_KEY                   – Bearer token
  APIGEE_PROXY_URL                 – Base URL, e.g. https://apihub-sandbox.dhl.com/genai-test
  APIGEE_DEFAULT_VERTEX_MODEL      – Fallback Vertex AI deployment ID
  APIGEE_DEFAULT_AZURE_OPENAI_MODEL – Fallback Azure OpenAI deployment ID
  AZURE_API_VERSION                – Azure API version (default: 2024-10-21)
  APIGEE_ENVIRONMENT               – "production" (default) | "testing"
  APIGEE_STREAMING_ENABLED         – "true" | "false" (default: false)
  APIGEE_TIMEOUT_SECONDS           – HTTP timeout in seconds (default: 60.0)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, AsyncGenerator

import httpx
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from .models_registry import Provider, get_model_info
from .settings import load_settings

_DEFAULT_API_VERSION = "2024-10-21"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parts_to_text(parts: list) -> str:
    """Join text parts into a single string."""
    return " ".join(p.text for p in parts if getattr(p, "text", None))


def _system_instruction_text(config: Any) -> str | None:
    """Extract the system instruction as plain text from a GenerateContentConfig."""
    si = getattr(config, "system_instruction", None) if config else None
    if not si:
        return None
    if isinstance(si, str):
        return si
    return _parts_to_text(getattr(si, "parts", [])) or None


def _streaming_enabled_from_env() -> bool:
    """Return True when APIGEE_STREAMING_ENABLED=true (case-insensitive)."""
    return load_settings().streaming_enabled


def _copy_if_set(src: Any, src_key: str, dst: dict, dst_key: str) -> None:
    """Copy src.src_key into dst[dst_key] only when the value is not None."""
    value = getattr(src, src_key, None)
    if value is not None:
        dst[dst_key] = value


# ---------------------------------------------------------------------------
# Part serializers
# ---------------------------------------------------------------------------

def _part_to_gemini_dict(part: Any) -> dict[str, Any] | None:
    """Serialize a single ADK Part to a Gemini REST API dict.

    Returns None for parts that cannot be serialized (skipped silently).
    Handles: text, inline_data (base64 image/audio), file_data (GCS URI),
             function_call, function_response, thought (thinking models).

    thought_signature is an opaque bytes blob that Gemini 2.5 thinking models
    attach to function_call parts.  It must be echoed back verbatim (as a
    base64 string) in the next request or the API returns 400 INVALID_ARGUMENT
    "missing a thought_signature".
    """
    # Thought part (thinking model internal reasoning — must be preserved)
    if getattr(part, "thought", None) is True:
        d: dict[str, Any] = {"thought": True}
        if getattr(part, "text", None) is not None:
            d["text"] = part.text
        sig = getattr(part, "thought_signature", None)
        if sig is not None:
            d["thoughtSignature"] = base64.b64encode(sig).decode("utf-8") if isinstance(sig, bytes) else sig
        return d
    if getattr(part, "text", None) is not None:
        return {"text": part.text}
    if getattr(part, "inline_data", None) is not None:
        blob = part.inline_data
        data = blob.data
        if isinstance(data, bytes):
            data = base64.b64encode(data).decode("utf-8")
        return {"inlineData": {"mimeType": blob.mime_type, "data": data}}
    if getattr(part, "file_data", None) is not None:
        fd = part.file_data
        return {"fileData": {"mimeType": fd.mime_type, "fileUri": fd.file_uri}}
    if getattr(part, "function_call", None) is not None:
        fc = part.function_call
        d = {"functionCall": {"name": fc.name, "args": fc.args or {}}}
        sig = getattr(part, "thought_signature", None)
        if sig is not None:
            d["thoughtSignature"] = base64.b64encode(sig).decode("utf-8") if isinstance(sig, bytes) else sig
        return d
    if getattr(part, "function_response", None) is not None:
        fr = part.function_response
        return {"functionResponse": {"name": fr.name, "response": fr.response or {}}}
    return None


def _part_to_openai_content(part: Any) -> dict[str, Any] | None:
    """Serialize a single ADK Part to an OpenAI content item.

    Returns None for non-serializable parts (skipped silently).
    Handles: text, inline_data (base64 image for vision models).
    Note: function_call/function_response are handled separately in the message loop.
    """
    if getattr(part, "text", None) is not None:
        return {"type": "text", "text": part.text}
    if getattr(part, "inline_data", None) is not None:
        blob = part.inline_data
        data = blob.data
        if isinstance(data, bytes):
            data = base64.b64encode(data).decode("utf-8")
        url = f"data:{blob.mime_type};base64,{data}"
        return {"type": "image_url", "image_url": {"url": url}}
    return None


# ---------------------------------------------------------------------------
# Tool / schema serializers
# ---------------------------------------------------------------------------

def _schema_to_dict(schema: Any, lowercase_types: bool = False) -> dict[str, Any]:
    """Recursively serialize a types.Schema to a plain dict for REST API payloads."""
    if schema is None:
        return {}
    result: dict[str, Any] = {}
    type_ = getattr(schema, "type_", None) or getattr(schema, "type", None)
    if type_ is not None:
        raw = type_.value if hasattr(type_, "value") else str(type_)
        result["type"] = raw.lower() if lowercase_types else raw.upper()
    description = getattr(schema, "description", None)
    if description:
        result["description"] = description
    properties = getattr(schema, "properties", None)
    if properties:
        result["properties"] = {
            k: _schema_to_dict(v, lowercase_types=lowercase_types)
            for k, v in properties.items()
        }
    required = getattr(schema, "required", None)
    if required:
        result["required"] = required
    items = getattr(schema, "items", None)
    if items is not None:
        result["items"] = _schema_to_dict(items, lowercase_types=lowercase_types)
    enum = getattr(schema, "enum", None)
    if enum:
        result["enum"] = enum
    return result


def _build_gemini_tools(config: Any) -> list[dict[str, Any]]:
    """Convert GenerateContentConfig.tools to Gemini REST tools array."""
    tools = getattr(config, "tools", None) if config else None
    if not tools:
        return []
    gemini_tools = []
    for tool in tools:
        fds = getattr(tool, "function_declarations", None) or []
        if not fds:
            continue
        declarations = []
        for fd in fds:
            decl: dict[str, Any] = {"name": fd.name}
            if fd.description:
                decl["description"] = fd.description
            if fd.parameters:
                decl["parameters"] = _schema_to_dict(fd.parameters, lowercase_types=False)
            elif getattr(fd, "parameters_json_schema", None):
                decl["parameters"] = fd.parameters_json_schema
            declarations.append(decl)
        if declarations:
            gemini_tools.append({"functionDeclarations": declarations})
    return gemini_tools


def _build_openai_tools(config: Any) -> list[dict[str, Any]]:
    """Convert GenerateContentConfig.tools to OpenAI REST tools array."""
    tools = getattr(config, "tools", None) if config else None
    if not tools:
        return []
    openai_tools = []
    for tool in tools:
        fds = getattr(tool, "function_declarations", None) or []
        for fd in fds:
            fn: dict[str, Any] = {"name": fd.name}
            if fd.description:
                fn["description"] = fd.description
            if fd.parameters:
                fn["parameters"] = _schema_to_dict(fd.parameters, lowercase_types=True)
            elif getattr(fd, "parameters_json_schema", None):
                fn["parameters"] = fd.parameters_json_schema
            openai_tools.append({"type": "function", "function": fn})
    return openai_tools


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def _should_retry(status_code: int) -> bool:
    return status_code in _RETRYABLE_STATUS_CODES


# ---------------------------------------------------------------------------
# Gemini response metadata parsers
# ---------------------------------------------------------------------------

def _parse_gemini_finish_reason(raw: str | None) -> types.FinishReason | None:
    if raw is None:
        return None
    try:
        return types.FinishReason[raw]
    except KeyError:
        return types.FinishReason.OTHER


def _parse_gemini_usage_metadata(
    data: dict | None,
) -> types.GenerateContentResponseUsageMetadata | None:
    if data is None:
        return None
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=data.get("promptTokenCount"),
        candidates_token_count=data.get("candidatesTokenCount"),
        total_token_count=data.get("totalTokenCount"),
    )


# ---------------------------------------------------------------------------
# Azure response metadata parsers
# ---------------------------------------------------------------------------

_AZURE_FINISH_REASON_MAP: dict[str, types.FinishReason] = {
    "stop": types.FinishReason.STOP,
    "length": types.FinishReason.MAX_TOKENS,
    "content_filter": types.FinishReason.SAFETY,
    "tool_calls": types.FinishReason.OTHER,
}


def _parse_azure_finish_reason(raw: str | None) -> types.FinishReason | None:
    if raw is None:
        return None
    return _AZURE_FINISH_REASON_MAP.get(raw, types.FinishReason.OTHER)


def _parse_azure_usage_metadata(
    data: dict | None,
) -> types.GenerateContentResponseUsageMetadata | None:
    if data is None:
        return None
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=data.get("prompt_tokens"),
        candidates_token_count=data.get("completion_tokens"),
        total_token_count=data.get("total_tokens"),
    )


# ---------------------------------------------------------------------------
# Vertex AI — Gemini GenerateContent format
# ---------------------------------------------------------------------------

def _build_gemini_payload(llm_request: LlmRequest) -> dict[str, Any]:
    """Convert an LlmRequest to a Gemini GenerateContent request body."""
    payload: dict[str, Any] = {
        "contents": [
            {
                "role": content.role,
                "parts": [
                    p_dict
                    for p in (content.parts or [])
                    if (p_dict := _part_to_gemini_dict(p)) is not None
                ],
            }
            for content in (llm_request.contents or [])
        ]
    }

    si_text = _system_instruction_text(llm_request.config)
    if si_text:
        payload["systemInstruction"] = {"parts": [{"text": si_text}]}

    gen_config = _build_gemini_generation_config(llm_request.config)
    if gen_config:
        payload["generationConfig"] = gen_config

    tools = _build_gemini_tools(llm_request.config)
    if tools:
        payload["tools"] = tools

    return payload


def _build_gemini_generation_config(config: Any) -> dict[str, Any]:
    """Extract all supported generation parameters from a GenerateContentConfig.

    Maps GenerateContentConfig fields → Gemini REST generationConfig keys.
    Only non-None values are included so the proxy uses its own defaults for
    anything not specified.
    """
    if not config:
        return {}

    gc: dict[str, Any] = {}

    _copy_if_set(config, "temperature",      gc, "temperature")
    _copy_if_set(config, "top_p",            gc, "topP")
    _copy_if_set(config, "top_k",            gc, "topK")
    _copy_if_set(config, "max_output_tokens", gc, "maxOutputTokens")
    _copy_if_set(config, "stop_sequences",   gc, "stopSequences")
    _copy_if_set(config, "candidate_count",  gc, "candidateCount")
    _copy_if_set(config, "presence_penalty", gc, "presencePenalty")
    _copy_if_set(config, "frequency_penalty", gc, "frequencyPenalty")
    _copy_if_set(config, "seed",             gc, "seed")
    _copy_if_set(config, "response_mime_type", gc, "responseMimeType")

    thinking = _build_gemini_thinking_config(getattr(config, "thinking_config", None))
    if thinking:
        gc["thinkingConfig"] = thinking

    return gc


def _build_gemini_thinking_config(thinking_config: Any) -> dict[str, Any]:
    """Map a ThinkingConfig object to the Gemini REST thinkingConfig dict."""
    if not thinking_config:
        return {}

    tc: dict[str, Any] = {}
    _copy_if_set(thinking_config, "thinking_budget",  tc, "thinkingBudget")
    _copy_if_set(thinking_config, "include_thoughts",  tc, "includeThoughts")

    level = getattr(thinking_config, "thinking_level", None)
    if level is not None:
        tc["thinkingBudget"] = _thinking_level_to_budget(level)

    return tc


def _thinking_level_to_budget(level: Any) -> int:
    """Convert ThinkingLevel enum to a token budget integer for the REST API."""
    name = getattr(level, "name", str(level)).upper()
    return {
        "THINKING_LEVEL_UNSPECIFIED": 0,
        "MINIMAL": 512,
        "LOW": 1024,
        "MEDIUM": 4096,
        "HIGH": 8192,
    }.get(name, 0)


def _gemini_candidate_to_response(candidate: dict[str, Any]) -> LlmResponse:
    """Convert a Gemini candidate to an LlmResponse, handling both text and function calls.

    Preserves thought parts and thought_signature bytes so that thinking-model
    multi-turn conversations replay correctly.  The Gemini 2.5 API requires the
    opaque thought_signature to be echoed back on the next turn when a
    function_call was produced by a thinking model; dropping it causes a 400
    "missing a thought_signature" error.
    """
    content = candidate.get("content") or {}
    raw_parts = content.get("parts") or []

    response_parts: list[types.Part] = []
    for raw_part in raw_parts:
        # Thought part — internal reasoning blob; must be preserved for multi-turn
        if raw_part.get("thought") is True:
            sig_raw = raw_part.get("thoughtSignature")
            sig_bytes = base64.b64decode(sig_raw) if isinstance(sig_raw, str) else sig_raw
            response_parts.append(
                types.Part(
                    thought=True,
                    text=raw_part.get("text"),
                    thought_signature=sig_bytes,
                )
            )
        elif "text" in raw_part:
            response_parts.append(types.Part(text=raw_part["text"]))
        elif "functionCall" in raw_part:
            fc = raw_part["functionCall"]
            sig_raw = raw_part.get("thoughtSignature")
            sig_bytes = base64.b64decode(sig_raw) if isinstance(sig_raw, str) else sig_raw
            response_parts.append(
                types.Part(
                    function_call=types.FunctionCall(name=fc["name"], args=fc.get("args") or {}),
                    thought_signature=sig_bytes,
                )
            )

    return LlmResponse(
        content=types.Content(role="model", parts=response_parts) if response_parts else None,
        finish_reason=_parse_gemini_finish_reason(candidate.get("finishReason")),
        turn_complete=True,
    )


def _parse_gemini_response(data: dict[str, Any]) -> LlmResponse:
    """Convert a Gemini GenerateContent (non-streaming) response to LlmResponse."""
    candidates = data.get("candidates") or []
    if not candidates:
        return LlmResponse(
            error_code="NO_CANDIDATES",
            error_message="Gemini response contained no candidates",
            turn_complete=True,
        )
    resp = _gemini_candidate_to_response(candidates[0])
    return resp.model_copy(update={"usage_metadata": _parse_gemini_usage_metadata(data.get("usageMetadata"))})


def _parse_gemini_chunk(data: dict[str, Any]) -> str:
    """Extract text from a single Gemini streaming chunk. Returns '' if no text."""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    return " ".join(p.get("text", "") for p in parts if p.get("text"))


class VertexAiRestLlm(BaseLlm):
    """Direct REST client for Vertex AI (Gemini) via the DHL Apigee proxy.

    Non-streaming:
      POST {proxy_url}/vertexai/publishers/google/models/{deployment_id}:generateContent
    Streaming:
      POST {proxy_url}/vertexai/publishers/google/models/{deployment_id}:streamGenerateContent
    Authorization: Bearer {api_key}
    """

    proxy_url: str
    api_key: str
    deployment_id: str
    streaming: bool = False
    max_retries: int = 3
    retry_initial_delay: float = 1.0
    timeout_seconds: float = 60.0

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"apigee-vertex\/.*"]

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        use_stream = stream or self.streaming
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = _build_gemini_payload(llm_request)

        if use_stream:
            url = (
                f"{self.proxy_url}/vertexai/publishers/google"
                f"/models/{self.deployment_id}:streamGenerateContent"
            )
            delay = self.retry_initial_delay
            for attempt in range(self.max_retries + 1):
                should_retry = False
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        async with client.stream("POST", url, json=payload, headers=headers) as resp:
                            if not resp.is_success:
                                body = await resp.aread()
                                if _should_retry(resp.status_code) and attempt < self.max_retries:
                                    should_retry = True
                                else:
                                    yield LlmResponse(
                                        error_code=str(resp.status_code),
                                        error_message=body.decode()[:500],
                                        turn_complete=True,
                                    )
                                    return
                            else:
                                last_finish_reason: str | None = None
                                last_usage_metadata = None
                                async for line in resp.aiter_lines():
                                    line = line.strip()
                                    if not line or line == "data: [DONE]":
                                        continue
                                    if line.startswith("data:"):
                                        line = line[5:].strip()
                                    try:
                                        chunk = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    # Capture metadata from chunk
                                    candidates = chunk.get("candidates") or []
                                    if candidates:
                                        candidate = candidates[0]
                                        if fr := candidate.get("finishReason"):
                                            last_finish_reason = fr
                                        content = candidate.get("content") or {}
                                        for raw_part in content.get("parts") or []:
                                            if raw_part.get("thought") is True:
                                                sig_raw = raw_part.get("thoughtSignature")
                                                sig_bytes = base64.b64decode(sig_raw) if isinstance(sig_raw, str) else sig_raw
                                                yield LlmResponse(
                                                    content=types.Content(role="model", parts=[types.Part(
                                                        thought=True,
                                                        text=raw_part.get("text"),
                                                        thought_signature=sig_bytes,
                                                    )]),
                                                    partial=True,
                                                    turn_complete=False,
                                                )
                                            elif "text" in raw_part and raw_part["text"]:
                                                yield LlmResponse(
                                                    content=types.Content(role="model", parts=[types.Part(text=raw_part["text"])]),
                                                    partial=True,
                                                    turn_complete=False,
                                                )
                                            elif "functionCall" in raw_part:
                                                fc = raw_part["functionCall"]
                                                sig_raw = raw_part.get("thoughtSignature")
                                                sig_bytes = base64.b64decode(sig_raw) if isinstance(sig_raw, str) else sig_raw
                                                yield LlmResponse(
                                                    content=types.Content(
                                                        role="model",
                                                        parts=[types.Part(
                                                            function_call=types.FunctionCall(
                                                                name=fc["name"], args=fc.get("args") or {}
                                                            ),
                                                            thought_signature=sig_bytes,
                                                        )],
                                                    ),
                                                    partial=True,
                                                    turn_complete=False,
                                                )
                                    if usage := chunk.get("usageMetadata"):
                                        last_usage_metadata = _parse_gemini_usage_metadata(usage)
                                yield LlmResponse(
                                    turn_complete=True,
                                    finish_reason=_parse_gemini_finish_reason(last_finish_reason),
                                    usage_metadata=last_usage_metadata,
                                )
                                return
                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt == self.max_retries:
                        raise
                    should_retry = True
                if should_retry:
                    await asyncio.sleep(delay)
                    delay *= 2
        else:
            url = (
                f"{self.proxy_url}/vertexai/publishers/google"
                f"/models/{self.deployment_id}:generateContent"
            )
            delay = self.retry_initial_delay
            resp = None
            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        resp = await client.post(url, json=payload, headers=headers)
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    if attempt == self.max_retries:
                        yield LlmResponse(
                            error_code="connection_error",
                            error_message=(
                                f"Could not reach the DHL GenAI Gateway at {self.proxy_url}. "
                                f"({type(exc).__name__}: {exc}). "
                                "Checklist: (1) Connect to the DHL corporate network / VPN — "
                                "the gateway rejects off-network requests. (2) If your network has no "
                                "direct route, uncomment HTTPS_PROXY/HTTP_PROXY in config/.env.apigee. "
                                "(3) For off-VPN testing, switch to OpenAI: cp config/.env.openai .env"
                            ),
                            turn_complete=True,
                        )
                        return
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if resp.is_success:
                    break
                if not _should_retry(resp.status_code) or attempt == self.max_retries:
                    break
                await asyncio.sleep(delay)
                delay *= 2

            if resp is None or not resp.is_success:
                yield LlmResponse(
                    error_code=str(resp.status_code) if resp is not None else "0",
                    error_message=resp.text[:500] if resp is not None else "No response (connect error after retries)",
                    turn_complete=True,
                )
                return

            yield _parse_gemini_response(resp.json())


# ---------------------------------------------------------------------------
# Azure OpenAI — OpenAI ChatCompletion format
# ---------------------------------------------------------------------------

def _build_openai_payload(llm_request: LlmRequest, stream: bool = False) -> dict[str, Any]:
    """Convert an LlmRequest to an OpenAI ChatCompletion request body."""
    messages: list[dict] = []

    si_text = _system_instruction_text(llm_request.config)
    if si_text:
        messages.append({"role": "system", "content": si_text})

    for content in llm_request.contents or []:
        role = "user" if content.role == "user" else "assistant"
        parts = content.parts or []

        content_items = [c for p in parts if (c := _part_to_openai_content(p)) is not None]

        if not content_items:
            continue

        if all(item["type"] == "text" for item in content_items):
            message_content: Any = " ".join(item["text"] for item in content_items)
        else:
            message_content = content_items

        messages.append({"role": role, "content": message_content})

    payload: dict[str, Any] = {"messages": messages}

    if llm_request.config:
        _copy_if_set(llm_request.config, "temperature",       payload, "temperature")
        _copy_if_set(llm_request.config, "top_p",             payload, "top_p")
        _copy_if_set(llm_request.config, "max_output_tokens", payload, "max_tokens")
        _copy_if_set(llm_request.config, "stop_sequences",    payload, "stop")
        _copy_if_set(llm_request.config, "presence_penalty",  payload, "presence_penalty")
        _copy_if_set(llm_request.config, "frequency_penalty", payload, "frequency_penalty")
        _copy_if_set(llm_request.config, "seed",              payload, "seed")
        _copy_if_set(llm_request.config, "candidate_count",   payload, "n")

    # Map response_mime_type to OpenAI response_format
    mime_type = getattr(llm_request.config, "response_mime_type", None) if llm_request.config else None
    if mime_type == "application/json":
        payload["response_format"] = {"type": "json_object"}

    tools = _build_openai_tools(llm_request.config)
    if tools:
        payload["tools"] = tools

    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

    return payload


def _openai_choice_to_response(choice: dict, usage_metadata: Any) -> LlmResponse:
    """Convert an OpenAI choice to an LlmResponse, handling text and tool calls."""
    message = choice.get("message") or {}
    response_parts: list[types.Part] = []

    text = message.get("content")
    if text:
        response_parts.append(types.Part(text=text))

    tool_calls = message.get("tool_calls") or []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        args_str = fn.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except json.JSONDecodeError:
            args = {}
        response_parts.append(
            types.Part(function_call=types.FunctionCall(name=name, args=args))
        )

    return LlmResponse(
        content=types.Content(role="model", parts=response_parts) if response_parts else None,
        finish_reason=_parse_azure_finish_reason(choice.get("finish_reason")),
        usage_metadata=usage_metadata,
        turn_complete=True,
    )


def _parse_openai_response(data: dict[str, Any]) -> LlmResponse:
    """Convert an OpenAI ChatCompletion (non-streaming) response to LlmResponse."""
    choices = data.get("choices") or []
    if not choices:
        return LlmResponse(
            error_code="NO_CHOICES",
            error_message="OpenAI response contained no choices",
            turn_complete=True,
        )
    usage_metadata = _parse_azure_usage_metadata(data.get("usage"))
    return _openai_choice_to_response(choices[0], usage_metadata)


def _parse_openai_chunk(data: dict[str, Any]) -> str:
    """Extract delta text from a single OpenAI streaming chunk. Returns '' if no text."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    return delta.get("content") or ""


class AzureOpenAiRestLlm(BaseLlm):
    """Direct REST client for Azure OpenAI via the DHL Apigee proxy.

    POST {proxy_url}/openai/deployments/{deployment_id}/chat/completions
         ?api-version={api_version}
    Authorization: Bearer {api_key}
    Streaming: adds {"stream": true} to the request body; response is SSE.
    """

    proxy_url: str
    api_key: str
    deployment_id: str
    api_version: str = _DEFAULT_API_VERSION
    streaming: bool = False
    max_retries: int = 3
    retry_initial_delay: float = 1.0
    timeout_seconds: float = 60.0

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"apigee-azure\/.*"]

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        use_stream = stream or self.streaming
        url = (
            f"{self.proxy_url}/openai/deployments/{self.deployment_id}"
            f"/chat/completions?api-version={self.api_version}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = _build_openai_payload(llm_request, stream=use_stream)

        if use_stream:
            delay = self.retry_initial_delay
            for attempt in range(self.max_retries + 1):
                should_retry = False
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        async with client.stream("POST", url, json=payload, headers=headers) as resp:
                            if not resp.is_success:
                                body = await resp.aread()
                                if _should_retry(resp.status_code) and attempt < self.max_retries:
                                    should_retry = True
                                else:
                                    yield LlmResponse(
                                        error_code=str(resp.status_code),
                                        error_message=body.decode()[:500],
                                        turn_complete=True,
                                    )
                                    return
                            else:
                                last_finish_reason: str | None = None
                                last_usage_metadata = None
                                tool_call_acc: dict[int, dict] = {}  # index → accumulated tool call

                                async for line in resp.aiter_lines():
                                    line = line.strip()
                                    if not line:
                                        continue
                                    if line.startswith("data:"):
                                        line = line[5:].strip()
                                    if line == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    # Capture top-level usage (from stream_options)
                                    if usage := chunk.get("usage"):
                                        last_usage_metadata = _parse_azure_usage_metadata(usage)
                                    choices = chunk.get("choices") or []
                                    if not choices:
                                        continue
                                    choice = choices[0]
                                    # Capture finish_reason
                                    if fr := choice.get("finish_reason"):
                                        last_finish_reason = fr
                                    delta = choice.get("delta") or {}
                                    # Accumulate tool call deltas
                                    for tc_delta in delta.get("tool_calls") or []:
                                        idx = tc_delta.get("index", 0)
                                        if idx not in tool_call_acc:
                                            tool_call_acc[idx] = {"name": "", "arguments": ""}
                                        fn = tc_delta.get("function") or {}
                                        if fn.get("name"):
                                            tool_call_acc[idx]["name"] += fn["name"]
                                        if fn.get("arguments"):
                                            tool_call_acc[idx]["arguments"] += fn["arguments"]
                                    # Yield text delta immediately
                                    text = delta.get("content") or ""
                                    if text:
                                        yield LlmResponse(
                                            content=types.Content(role="model", parts=[types.Part(text=text)]),
                                            partial=True,
                                            turn_complete=False,
                                        )

                                # Yield accumulated tool calls as partial responses
                                for idx in sorted(tool_call_acc.keys()):
                                    tc = tool_call_acc[idx]
                                    try:
                                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                                    except json.JSONDecodeError:
                                        args = {}
                                    yield LlmResponse(
                                        content=types.Content(
                                            role="model",
                                            parts=[types.Part(function_call=types.FunctionCall(name=tc["name"], args=args))],
                                        ),
                                        partial=True,
                                        turn_complete=False,
                                    )

                                yield LlmResponse(
                                    turn_complete=True,
                                    finish_reason=_parse_azure_finish_reason(last_finish_reason),
                                    usage_metadata=last_usage_metadata,
                                )
                                return
                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt == self.max_retries:
                        raise
                    should_retry = True
                if should_retry:
                    await asyncio.sleep(delay)
                    delay *= 2
        else:
            delay = self.retry_initial_delay
            resp = None
            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        resp = await client.post(url, json=payload, headers=headers)
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    if attempt == self.max_retries:
                        yield LlmResponse(
                            error_code="connection_error",
                            error_message=(
                                f"Could not reach the DHL GenAI Gateway at {self.proxy_url}. "
                                f"({type(exc).__name__}: {exc}). "
                                "Checklist: (1) Connect to the DHL corporate network / VPN — "
                                "the gateway rejects off-network requests. (2) If your network has no "
                                "direct route, uncomment HTTPS_PROXY/HTTP_PROXY in config/.env.apigee. "
                                "(3) For off-VPN testing, switch to OpenAI: cp config/.env.openai .env"
                            ),
                            turn_complete=True,
                        )
                        return
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if resp.is_success:
                    break
                if not _should_retry(resp.status_code) or attempt == self.max_retries:
                    break
                await asyncio.sleep(delay)
                delay *= 2

            if resp is None or not resp.is_success:
                yield LlmResponse(
                    error_code=str(resp.status_code) if resp is not None else "0",
                    error_message=resp.text[:500] if resp is not None else "No response (connect error after retries)",
                    turn_complete=True,
                )
                return

            yield _parse_openai_response(resp.json())


# ---------------------------------------------------------------------------
# OpenAI Direct — standard api.openai.com endpoint
# ---------------------------------------------------------------------------

class OpenAiDirectLlm(BaseLlm):
    """Direct REST client for the standard OpenAI API (api.openai.com).

    POST https://api.openai.com/v1/chat/completions
    Authorization: Bearer {OPENAI_API_KEY}

    Unlike AzureOpenAiRestLlm the model is specified in the request body,
    not in the URL path, and there is no api-version query parameter.
    """

    api_key: str
    model_id: str          # e.g. "gpt-4o", "gpt-4o-mini", "gpt-4-turbo"
    streaming: bool = False
    max_retries: int = 3
    retry_initial_delay: float = 1.0
    timeout_seconds: float = 60.0

    _ENDPOINT: str = "https://api.openai.com/v1/chat/completions"

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"openai-direct\/.*"]

    async def generate_content_async(
        self,
        llm_request: LlmRequest,
        stream: bool = False,
    ) -> AsyncGenerator[LlmResponse, None]:
        use_stream = stream or self.streaming
        payload = _build_openai_payload(llm_request, stream=use_stream)
        payload["model"] = self.model_id   # required field for direct OpenAI API

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if use_stream:
            delay = self.retry_initial_delay
            for attempt in range(self.max_retries + 1):
                should_retry = False
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        async with client.stream("POST", self._ENDPOINT, json=payload, headers=headers) as resp:
                            if not resp.is_success:
                                body = await resp.aread()
                                if _should_retry(resp.status_code) and attempt < self.max_retries:
                                    should_retry = True
                                else:
                                    yield LlmResponse(
                                        error_code=str(resp.status_code),
                                        error_message=body.decode()[:500],
                                        turn_complete=True,
                                    )
                                    return
                            else:
                                last_finish_reason: str | None = None
                                last_usage_metadata = None
                                tool_call_acc: dict[int, dict] = {}

                                async for line in resp.aiter_lines():
                                    line = line.strip()
                                    if not line:
                                        continue
                                    if line.startswith("data:"):
                                        line = line[5:].strip()
                                    if line == "[DONE]":
                                        break
                                    try:
                                        chunk = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    if usage := chunk.get("usage"):
                                        last_usage_metadata = _parse_azure_usage_metadata(usage)
                                    choices = chunk.get("choices") or []
                                    if not choices:
                                        continue
                                    choice = choices[0]
                                    if fr := choice.get("finish_reason"):
                                        last_finish_reason = fr
                                    delta = choice.get("delta") or {}
                                    for tc_delta in delta.get("tool_calls") or []:
                                        idx = tc_delta.get("index", 0)
                                        if idx not in tool_call_acc:
                                            tool_call_acc[idx] = {"name": "", "arguments": ""}
                                        fn = tc_delta.get("function") or {}
                                        if fn.get("name"):
                                            tool_call_acc[idx]["name"] += fn["name"]
                                        if fn.get("arguments"):
                                            tool_call_acc[idx]["arguments"] += fn["arguments"]
                                    text = delta.get("content") or ""
                                    if text:
                                        yield LlmResponse(
                                            content=types.Content(role="model", parts=[types.Part(text=text)]),
                                            partial=True,
                                            turn_complete=False,
                                        )

                                for idx in sorted(tool_call_acc.keys()):
                                    tc = tool_call_acc[idx]
                                    try:
                                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                                    except json.JSONDecodeError:
                                        args = {}
                                    yield LlmResponse(
                                        content=types.Content(
                                            role="model",
                                            parts=[types.Part(function_call=types.FunctionCall(name=tc["name"], args=args))],
                                        ),
                                        partial=True,
                                        turn_complete=False,
                                    )

                                yield LlmResponse(
                                    turn_complete=True,
                                    finish_reason=_parse_azure_finish_reason(last_finish_reason),
                                    usage_metadata=last_usage_metadata,
                                )
                                return
                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt == self.max_retries:
                        raise
                    should_retry = True
                if should_retry:
                    await asyncio.sleep(delay)
                    delay *= 2
        else:
            delay = self.retry_initial_delay
            resp = None
            for attempt in range(self.max_retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                        resp = await client.post(self._ENDPOINT, json=payload, headers=headers)
                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt == self.max_retries:
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                if resp.is_success:
                    break
                if not _should_retry(resp.status_code) or attempt == self.max_retries:
                    break
                await asyncio.sleep(delay)
                delay *= 2

            if resp is None or not resp.is_success:
                yield LlmResponse(
                    error_code=str(resp.status_code) if resp is not None else "0",
                    error_message=resp.text[:500] if resp is not None else "No response",
                    turn_complete=True,
                )
                return

            yield _parse_openai_response(resp.json())


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

def build_vertex_ai_rest_model(
    deployment_id: str | None = None,
    streaming: bool | None = None,
    timeout_seconds: float | None = None,
) -> VertexAiRestLlm:
    """Return a VertexAiRestLlm for the given (or default) Vertex AI deployment.

    Args:
        deployment_id: Deployment ID. Falls back to APIGEE_DEFAULT_VERTEX_MODEL.
        streaming: Enable streaming. None → read APIGEE_STREAMING_ENABLED env var.
        timeout_seconds: HTTP timeout. None → read APIGEE_TIMEOUT_SECONDS env var.

    Raises:
        KeyError: If a required env var (APIGEE_API_KEY, proxy URL, deployment ID) is absent.
        ValueError: If the deployment ID is not in the active model registry.
    """
    s = load_settings()
    if not s.api_key:
        raise KeyError("APIGEE_API_KEY")
    if not s.proxy_url:
        raise KeyError("APIGEE_PROXY_URL")
    resolved_id = deployment_id or s.default_vertex_model
    if not resolved_id:
        raise KeyError("APIGEE_DEFAULT_VERTEX_MODEL")
    use_streaming = streaming if streaming is not None else s.streaming_enabled
    resolved_timeout = timeout_seconds if timeout_seconds is not None else s.timeout_seconds

    get_model_info(resolved_id)  # validate

    return VertexAiRestLlm(
        model=f"apigee-vertex/{resolved_id}",
        proxy_url=s.proxy_url,
        api_key=s.api_key,
        deployment_id=resolved_id,
        streaming=use_streaming,
        timeout_seconds=resolved_timeout,
    )


def build_azure_rest_model(
    deployment_id: str | None = None,
    streaming: bool | None = None,
    timeout_seconds: float | None = None,
) -> AzureOpenAiRestLlm:
    """Return an AzureOpenAiRestLlm for the given (or default) Azure deployment.

    Args:
        deployment_id: Deployment ID. Falls back to APIGEE_DEFAULT_AZURE_OPENAI_MODEL.
        streaming: Enable streaming. None → read APIGEE_STREAMING_ENABLED env var.
        timeout_seconds: HTTP timeout. None → read APIGEE_TIMEOUT_SECONDS env var.

    Raises:
        KeyError: If a required env var (APIGEE_API_KEY, proxy URL, deployment ID) is absent.
        ValueError: If the deployment ID is not in the active model registry.
    """
    s = load_settings()
    if not s.api_key:
        raise KeyError("APIGEE_API_KEY")
    if not s.proxy_url:
        raise KeyError("APIGEE_PROXY_URL")
    resolved_id = deployment_id or s.default_azure_model
    if not resolved_id:
        raise KeyError("APIGEE_DEFAULT_AZURE_OPENAI_MODEL")
    use_streaming = streaming if streaming is not None else s.streaming_enabled
    resolved_timeout = timeout_seconds if timeout_seconds is not None else s.timeout_seconds

    get_model_info(resolved_id)  # validate

    return AzureOpenAiRestLlm(
        model=f"apigee-azure/{resolved_id}",
        proxy_url=s.proxy_url,
        api_key=s.api_key,
        deployment_id=resolved_id,
        api_version=s.azure_api_version,
        streaming=use_streaming,
        timeout_seconds=resolved_timeout,
    )


def build_openai_direct_model(
    model_id: str | None = None,
    streaming: bool | None = None,
    timeout_seconds: float | None = None,
) -> OpenAiDirectLlm:
    """Return an OpenAiDirectLlm targeting api.openai.com.

    Args:
        model_id: OpenAI model name (e.g. "gpt-4o", "gpt-4o-mini").
                  Falls back to OPENAI_MODEL env var, then "gpt-4o-mini".
        streaming: Enable streaming. None → read APIGEE_STREAMING_ENABLED env var.
        timeout_seconds: HTTP timeout. None → read APIGEE_TIMEOUT_SECONDS env var.

    Raises:
        KeyError: If OPENAI_API_KEY is not set.
    """
    import os

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise KeyError(
            "OPENAI_API_KEY is not set. "
            "Export it or add it to your .env file before using openai mode."
        )

    s = load_settings()
    resolved_id = model_id or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    use_streaming = streaming if streaming is not None else s.streaming_enabled
    resolved_timeout = timeout_seconds if timeout_seconds is not None else s.timeout_seconds

    return OpenAiDirectLlm(
        model=f"openai-direct/{resolved_id}",
        api_key=api_key,
        model_id=resolved_id,
        streaming=use_streaming,
        timeout_seconds=resolved_timeout,
    )


def build_model_for_env(
    deployment_id: str | None = None,
    streaming: bool | None = None,
    timeout_seconds: float | None = None,
) -> "VertexAiRestLlm | AzureOpenAiRestLlm | OpenAiDirectLlm | str":
    """Select the LLM backend based on the CCRE_LLM_MODE environment variable.

    Modes
    -----
    stub      — :class:`StubLlm`: scripted responses, no HTTP calls, no keys needed.
    openai    — :class:`OpenAiDirectLlm`: direct api.openai.com via OPENAI_API_KEY.
    google-ai — Native Gemini via Google AI Studio (GOOGLE_API_KEY).
                Returns a model-name string that ADK resolves automatically.
    apigee    — (default) DHL Apigee proxy via :func:`build_rest_model`.

    Args:
        deployment_id: Forwarded to build_rest_model() for apigee mode only.
        streaming:     Forwarded to the underlying factory.
        timeout_seconds: Forwarded to the underlying factory.

    Returns:
        A BaseLlm instance or a model-name string (google-ai mode).
    """
    import os

    mode = os.getenv("CCRE_LLM_MODE", "apigee").lower().strip()

    if mode == "stub":
        from .stub_llm import build_stub_model
        return build_stub_model()

    if mode == "openai":
        return build_openai_direct_model(streaming=streaming, timeout_seconds=timeout_seconds)

    if mode == "google-ai":
        model_id = os.getenv("GOOGLE_AI_MODEL", "gemini-2.0-flash-001")
        return model_id  # ADK resolves a string model name via GOOGLE_API_KEY

    # Default: DHL Apigee proxy
    return build_rest_model(deployment_id, streaming=streaming, timeout_seconds=timeout_seconds)


def build_rest_model(
    deployment_id: str | None = None,
    streaming: bool | None = None,
    timeout_seconds: float | None = None,
) -> VertexAiRestLlm | AzureOpenAiRestLlm:
    """Auto-routing factory — selects provider from the model registry.

    Args:
        deployment_id: Deployment ID. Falls back to APIGEE_DEFAULT_VERTEX_MODEL,
                   then APIGEE_DEFAULT_AZURE_OPENAI_MODEL.
        streaming: Enable streaming. None → read APIGEE_STREAMING_ENABLED env var.
        timeout_seconds: HTTP timeout. None → read APIGEE_TIMEOUT_SECONDS env var.

    Raises:
        KeyError: If a required env var is absent.
        ValueError: If the deployment ID is not in the active model registry.
    """
    s = load_settings()
    resolved_id = deployment_id or s.default_vertex_model or s.default_azure_model
    if not resolved_id:
        raise KeyError("APIGEE_DEFAULT_VERTEX_MODEL")

    info = get_model_info(resolved_id)

    if info.provider == Provider.VERTEX_AI:
        return build_vertex_ai_rest_model(resolved_id, streaming=streaming, timeout_seconds=timeout_seconds)

    return build_azure_rest_model(resolved_id, streaming=streaming, timeout_seconds=timeout_seconds)
