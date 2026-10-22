"""The agent harness: error format, output envelope, context building and tool registry.

Design: ``docs/design/agent-design.md`` ("Harness engineering", "The agent
contract", "Tool catalogue"); decision record ``docs/adr/0002``. The populated
catalogue lives in :mod:`tools.agents.harness.catalogue` and is imported
explicitly, because its tools need the database.
"""
from __future__ import annotations

from .context import ContextBuilder, wrap_untrusted
from .envelope import AgentOutput, SourceRef
from .errors import GateError, GateResult
from .registry import (
    AGENT_NAMES,
    CallScope,
    RegistrationError,
    ScopeError,
    ToolArgumentError,
    ToolError,
    ToolNotAllowedError,
    ToolRegistry,
    ToolSpec,
    UnknownToolError,
)

__all__ = [
    "AGENT_NAMES", "AgentOutput", "CallScope", "ContextBuilder", "GateError", "GateResult",
    "RegistrationError", "ScopeError", "SourceRef", "ToolArgumentError", "ToolError",
    "ToolNotAllowedError", "ToolRegistry", "ToolSpec", "UnknownToolError", "wrap_untrusted",
]
