"""JSON extraction utilities — no ADK dependency, safe to import anywhere."""
from __future__ import annotations

import json
import re
import sys
from typing import Any

_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL | re.IGNORECASE)


class AgentInvocationError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """Extract JSON from agent response.

    Searches for the LAST fenced JSON block first, then falls back to the last
    raw JSON object in the text. Using the last occurrence handles the common
    pattern where a model reasons first and then produces the final JSON answer.
    """
    # Strategy 1: find ALL ```json fences, take the last valid one
    all_fences = list(_JSON_FENCE.finditer(text))
    for m in reversed(all_fences):
        try:
            result = json.loads(m.group(1))
            print("[JSON_EXTRACT] Fenced JSON parsed successfully (last fence)", file=sys.stderr)
            return result
        except json.JSONDecodeError as e:
            print(f"[JSON_EXTRACT] Fenced JSON invalid, trying earlier fence: {e}", file=sys.stderr)

    # Strategy 2: walk the string right-to-left to find the last complete JSON object
    stripped = text.strip()
    end = len(stripped) - 1
    while end >= 0:
        if stripped[end] == "}":
            depth = 0
            for i in range(end, -1, -1):
                if stripped[i] == "}":
                    depth += 1
                elif stripped[i] == "{":
                    depth -= 1
                    if depth == 0:
                        try:
                            result = json.loads(stripped[i:end + 1])
                            print("[JSON_EXTRACT] Raw JSON parsed successfully (last object)", file=sys.stderr)
                            return result
                        except json.JSONDecodeError as e:
                            print(f"[JSON_EXTRACT] Raw JSON candidate invalid: {e}", file=sys.stderr)
                        break
        end -= 1

    print(f"[JSON_EXTRACT] No JSON found. Response starts: {text[:200]}", file=sys.stderr)
    raise ValueError(f"No JSON object found in agent response (first 200 chars: {text[:200]})")
