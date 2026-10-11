"""UAT execution — payload generation support, executors, mock CCRE, response checks.

Flow per approved test case (driven by ``server.lifecycle``):

    sample payload ─► payload_generator agent (or payload_builder) ─► executor
                   ─► checker (deterministic) ─► response_reviewer agent ─► result
"""
import json
from pathlib import Path

from .checker import check_response, resolve
from .executor import ExecutionOutcome, Executor, build_executor
from .payload_builder import build_payload

SAMPLE_PAYLOAD_PATH = Path(__file__).parent / "sample_payload.json"


def builtin_sample_payload() -> dict:
    return json.loads(SAMPLE_PAYLOAD_PATH.read_text(encoding="utf-8"))


__all__ = [
    "ExecutionOutcome", "Executor", "build_executor", "build_payload", "builtin_sample_payload",
    "check_response", "resolve",
]
