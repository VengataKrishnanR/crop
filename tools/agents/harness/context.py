"""Context assembly for agent calls.

Each agent gets a small, assembled context per call, in a fixed section order,
with untrusted data (business free text, workbook cells, CRMS responses) inside
delimiters the system prompt declares as data, never instructions (agent
contract, rule 10). Per-agent builders subclass :class:`ContextBuilder` and
declare ``SECTIONS`` (Phase 4).
"""
from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Literal

UntrustedKind = Literal["business_text", "workbook_rows", "crms_response"]
UNTRUSTED_KINDS: tuple[str, ...] = ("business_text", "workbook_rows", "crms_response")

# Any opening or closing delimiter tag, tolerant of case and whitespace, so text
# cannot close its own block early ("</business_text>") or open a fake one.
_TAG = re.compile(r"<\s*(/?)\s*(" + "|".join(UNTRUSTED_KINDS) + r")\s*>", re.IGNORECASE)


def _escape(text: str) -> str:
    return _TAG.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}&gt;", text)


def wrap_untrusted(kind: UntrustedKind, data: Any) -> str:
    """Quote untrusted data inside its delimiter. Non-strings are rendered as JSON."""
    if kind not in UNTRUSTED_KINDS:
        raise ValueError(f"Unknown untrusted kind {kind!r}.")
    text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str, ensure_ascii=False)
    return f"<{kind}>\n{_escape(text)}\n</{kind}>"


class ContextBuilder:
    """Assembles named sections in the order declared by ``SECTIONS``.

    Sections not in ``SECTIONS`` are refused, so an agent's context is exactly
    what its card lists. Missing sections are omitted rather than invented.
    """

    SECTIONS: ClassVar[tuple[str, ...]] = ()

    def __init__(self) -> None:
        self._parts: dict[str, str] = {}

    def add(self, section: str, content: Any) -> "ContextBuilder":
        if section not in self.SECTIONS:
            raise KeyError(f"{type(self).__name__} has no section {section!r}; declared: {self.SECTIONS}.")
        body = content if isinstance(content, str) else json.dumps(content, indent=2, default=str,
                                                                 ensure_ascii=False)
        self._parts[section] = body
        return self

    def add_untrusted(self, section: str, kind: UntrustedKind, data: Any) -> "ContextBuilder":
        return self.add(section, wrap_untrusted(kind, data))

    def build(self) -> str:
        return "\n\n".join(f"## {name}\n{self._parts[name]}" for name in self.SECTIONS if name in self._parts)
