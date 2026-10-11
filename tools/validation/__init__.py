"""Deterministic validation.

This package is the platform's authority. Nothing here consults a model, and no
caller may override a blocker -- the workflow reads the report and refuses to
advance. Keeping that property is the whole point of the architecture.
"""
from __future__ import annotations

from typing import Optional, Sequence

from sqlalchemy.orm import Session

from tools.core.models import ValidationRun
from . import checks as _checks
from .report import Finding, ValidationReport
from .snapshot import Snapshot, load_snapshot

__all__ = [
    "Finding", "ValidationReport", "Snapshot", "load_snapshot",
    "run_checks", "validate_rule_set", "available_checks",
]


def available_checks() -> dict[str, str]:
    return dict(_checks.DESCRIPTIONS)


def run_checks(snapshot: Snapshot, only: Optional[Sequence[str]] = None) -> ValidationReport:
    """Run the register against a snapshot."""
    report = ValidationReport()
    codes = list(only) if only else list(_checks.REGISTRY)
    for code in codes:
        fn = _checks.REGISTRY.get(code)
        if fn is None:
            continue
        report.checks_run.append(code)
        report.findings.extend(fn(snapshot))
    return report


def validate_rule_set(
    session: Session,
    rule_set_id: str,
    case_id: Optional[str] = None,
    persist: bool = True,
) -> tuple[ValidationReport, Optional[str]]:
    """Validate a rule set and optionally record the run as evidence.

    Returns the report and the persisted run id, if any.
    """
    snapshot = load_snapshot(session, rule_set_id=rule_set_id)
    report = run_checks(snapshot)

    run_id: Optional[str] = None
    if persist:
        run = ValidationRun(
            case_id=case_id,
            rule_set_id=rule_set_id,
            blocker_count=len(report.blockers),
            caution_count=len(report.cautions),
            info_count=len(report.infos),
            findings=[f.as_dict() for f in report.sorted()],
        )
        session.add(run)
        session.flush()
        run_id = run.id

    return report, run_id
