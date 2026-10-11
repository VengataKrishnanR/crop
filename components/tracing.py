"""ADK Web trace display fix — copied verbatim from the ReAct skeleton.

Patches ``use_generate_content_span`` to strip ``invocation_id`` from the inner
``generate_content`` span so ADK Web can parse the LLM request JSON correctly.
This is a display-only fix; agent functionality is unaffected.
"""

from __future__ import annotations

from contextlib import contextmanager

import google.adk.telemetry.tracing as _adk_tracing

_INVOCATION_ID_KEY = "gcp.vertex.agent.invocation_id"

_original_use_gc_span = _adk_tracing.use_generate_content_span


@contextmanager
def _patched_use_gc_span(llm_request, invocation_context, model_response_event):
    _original_native = _adk_tracing._use_native_generate_content_span

    @contextmanager
    def _filtered_native(llm_request, common_attributes):
        filtered = {k: v for k, v in common_attributes.items() if k != _INVOCATION_ID_KEY}
        with _original_native(llm_request=llm_request, common_attributes=filtered) as span:
            yield span

    _adk_tracing._use_native_generate_content_span = _filtered_native
    try:
        with _original_use_gc_span(llm_request, invocation_context, model_response_event) as span:
            yield span
    finally:
        _adk_tracing._use_native_generate_content_span = _original_native


def apply_tracing_patch() -> None:
    """Apply the ``generate_content`` span patch (idempotent)."""
    if _adk_tracing.use_generate_content_span is not _patched_use_gc_span:
        _adk_tracing.use_generate_content_span = _patched_use_gc_span
