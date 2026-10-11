"""Finding and snapshot types shared by every check."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Severity = Literal["blocker", "caution", "info"]

_ORDER: dict[str, int] = {"blocker": 0, "caution": 1, "info": 2}


@dataclass
class Finding:
    """One validation result.

    Findings are produced only by deterministic checks. A blocker cannot be
    overridden in the UI -- it has to be fixed, or the rule set does not advance.
    """

    code: str
    severity: Severity
    where: str
    message: str
    evidence: Optional[str] = None
    subjects: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "where": self.where,
            "message": self.message,
            "evidence": self.evidence,
            "subjects": self.subjects,
            "counts": self.counts,
        }


@dataclass
class ValidationReport:
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocker"]

    @property
    def cautions(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "caution"]

    @property
    def infos(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "info"]

    @property
    def is_clean(self) -> bool:
        """Clean means nothing blocking. Cautions are accepted by a human."""
        return not self.blockers

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (_ORDER[f.severity], f.code))

    def as_dict(self) -> dict[str, Any]:
        return {
            "clean": self.is_clean,
            "blocker_count": len(self.blockers),
            "caution_count": len(self.cautions),
            "info_count": len(self.infos),
            "checks_run": self.checks_run,
            "findings": [f.as_dict() for f in self.sorted()],
        }


def sample(values: Any, limit: int = 8) -> list[str]:
    """A short, stable sample for a finding that summarises many rows."""
    return [str(v) for v in sorted(values)[:limit]]
