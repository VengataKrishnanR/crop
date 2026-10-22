"""The one error format every deterministic gate speaks.

A gate that only says "invalid" ends an agent run; one that says *which field,
which rule, what was expected* lets the agent repair itself in one retry
(design: "every gate speaks to the agent"). ``path`` locates the problem in the
agent's output (``rows[2].other_logic``, ``milestones[3].start``); ``hint`` says
what would make it pass.
"""
from __future__ import annotations

from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["error", "warning"]


class GateError(BaseModel):
    """One machine-readable gate finding."""

    code: str = Field(min_length=1)
    path: str
    message: str = Field(min_length=1)
    hint: Optional[str] = None
    severity: Severity = "error"


class GateResult(BaseModel):
    """Outcome of one gate. ``passed`` is false only when an *error* is present."""

    passed: bool
    errors: list[GateError] = Field(default_factory=list)

    @classmethod
    def ok(cls) -> "GateResult":
        return cls(passed=True, errors=[])

    @classmethod
    def from_errors(cls, errors: Iterable[GateError]) -> "GateResult":
        items = list(errors)
        return cls(passed=not any(e.severity == "error" for e in items), errors=items)

    @property
    def blocking(self) -> list[GateError]:
        return [e for e in self.errors if e.severity == "error"]

    @property
    def warnings(self) -> list[GateError]:
        return [e for e in self.errors if e.severity == "warning"]

    def merge(self, *others: "GateResult") -> "GateResult":
        return GateResult.from_errors([*self.errors, *(e for o in others for e in o.errors)])
