"""Deterministic validation.

This package is the platform's authority. Nothing here consults a model, and no
caller may override a blocker -- the workflow reads the report and refuses to
advance. Keeping that property is the whole point of the architecture.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Sequence

from sqlalchemy.orm import Session

from tools.core.models import ValidationRun
from . import checks as _checks
from .report import Finding, ValidationReport
from .snapshot import Snapshot, load_snapshot

if TYPE_CHECKING:
    from tools.agents.harness.errors import GateResult

__all__ = [
    "Finding", "ValidationReport", "Snapshot", "load_snapshot",
    "run_checks", "validate_rule_set", "available_checks", "gate_findings",
]

# Rule-level checks: the rule field each one is about. Findings of these checks
# name rule ids in ``subjects``, so they become one GateError per rule.
_RULE_FIELDS: dict[str, str] = {
    "CHK005": "bindings.attribute_ids",
    "CHK009": "bindings",
    "CHK010": "other_logic",
    "CHK014": "min_value",
}

_HINTS: dict[str, str] = {
    "CHK002": "Use a requirement group defined in the active package, or request a package rebuild.",
    "CHK003": "Bind only definitions the package ships; list the missing one as a package gap.",
    "CHK005": "Pick attribute ids from the definition's attribute list (get_package_definition).",
    "CHK007": "Copy the component name exactly from the package definition.",
    "CHK009": "Bind the rule to at least one requirement definition, or replace the TEST placeholder.",
    "CHK012": "Use a value from the workbook's Validation list for this field.",
    "CHK014": "Set a minimum or maximum value, or state that the requirement is value-independent.",
    "CHK015": "Request a package rebuild that maps the country before testing.",
    "CHK016": "Leave Document Reference to the generated country|direction|countryHold|globalHold form.",
}


def gate_findings(report: ValidationReport) -> "GateResult":
    """The 16-check register as a :class:`GateResult`.

    blocker -> error, caution -> warning, info -> dropped (evidence only).
    """
    from tools.agents.harness.errors import GateError, GateResult
    from tools.core import grammar

    errors: list[GateError] = []
    for f in report.sorted():
        if f.severity == "info":
            continue
        severity = "error" if f.severity == "blocker" else "warning"
        base = f.code.split("/")[0]
        if base == "CHK010" and "/" in f.code:
            hint = grammar.diagnostic_hint(f.code.split("/", 1)[1])
        else:
            hint = _HINTS.get(base) or f.evidence
        field = _RULE_FIELDS.get(base)
        if base == "CHK012" and "·" in f.where:
            field = f.where.split("·", 1)[1].strip()
        if field and f.subjects:
            errors.extend(GateError(code=f.code, path=f"rules[{s}].{field}", message=f.message, hint=hint,
                                    severity=severity) for s in f.subjects)
        else:
            errors.append(GateError(code=f.code, path=f.where, message=f.message, hint=hint, severity=severity))
    return GateResult.from_errors(errors)


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
