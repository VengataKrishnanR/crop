"""The typed output envelope every agent returns (agent contract, rule 3).

``suggestion`` follows the agent's own schema; the rest is the same for all
agents so the UI, the run log and the feedback loops treat them uniformly.
Every value in a suggestion points to a :class:`SourceRef` or is listed in
``assumptions`` (rule 4, "cite or flag").
"""
from __future__ import annotations

from typing import Generic, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

SourceKind = Literal[
    "requirement_field",
    "m2c_row",
    "package_definition",
    "calendar",
    "crms_field",
    "crms_response",
    "audit_event",
]

T = TypeVar("T")


class SourceRef(BaseModel):
    """Where a suggested value came from."""

    kind: SourceKind
    ref: str = Field(min_length=1)
    detail: Optional[str] = None


class AgentOutput(BaseModel, Generic[T]):
    """``{suggestion, rationale, assumptions[], open_questions[], confidence, sources[]}``."""

    suggestion: T
    rationale: str
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    sources: list[SourceRef] = Field(default_factory=list)
